from __future__ import annotations

from functools import wraps
from typing import Any, Callable, Dict, Optional, Tuple

from .settings import is_trace_enabled
from .trace import emit

_LAST_STEP: Dict[str, str] = {}
_LAST_GATE: Dict[str, Tuple[str, bool]] = {}


def _extract_prereq(label: str) -> Optional[str]:
    if not label:
        return None
    prefix = label.strip().split(" ", 1)[0]
    if prefix.upper().startswith("P") and len(prefix) == 2 and prefix[1].isdigit():
        return prefix.upper()
    return None


def _thread_id_from_state(state: Any) -> str:
    if not state:
        return "unknown-thread"
    thread_id = getattr(state, "thread_id", None)
    if not thread_id:
        client_id = getattr(state, "client_id", None)
        if client_id:
            thread_id = str(client_id)
        else:
            message = getattr(state, "message", None)
            if message and getattr(message, "msg_id", None):
                thread_id = message.msg_id
    return str(thread_id or "unknown-thread")


def trace_step(step_name: str):
    def deco(fn: Callable):
        @wraps(fn)
        def inner(*args, **kwargs):
            state = kwargs.get("state")
            if state is None and args:
                state = args[0]
            thread_id = _thread_id_from_state(state)
            loop = _LAST_STEP.get(thread_id) == step_name
            _LAST_STEP[thread_id] = step_name
            emit(
                thread_id,
                "STEP_ENTER",
                step=step_name,
                owner_step=step_name,
                subject=step_name,
                status="checked",
                loop=loop,
                granularity="logic",
            )
            try:
                return fn(*args, **kwargs)
            finally:
                emit(
                    thread_id,
                    "STEP_EXIT",
                    step=step_name,
                    owner_step=step_name,
                    subject=step_name,
                    status="checked",
                    granularity="logic",
                )

        return inner

    return deco


def trace_gate(
    thread_id: str,
    owner_step: str,
    gate_label: str,
    ok: bool,
    inputs: Optional[Dict[str, Any]] = None,
    *,
    granularity: str = "logic",
) -> None:
    previous = _LAST_GATE.get(thread_id)
    loop = bool(previous and previous[0] == gate_label)
    _LAST_GATE[thread_id] = (gate_label, ok)
    gate_payload: Dict[str, Any] = {
        "label": gate_label,
        "result": "PASS" if ok else "FAIL",
    }
    prereq = _extract_prereq(gate_label)
    if prereq:
        gate_payload["prereq"] = prereq
    if inputs:
        gate_payload["inputs"] = inputs
    emit(
        thread_id,
        "GATE_PASS" if ok else "GATE_FAIL",
        step=owner_step,
        owner_step=owner_step,
        detail=gate_label,
        data=inputs or {},
        subject=gate_label,
        status="pass" if ok else "fail",
        loop=loop,
        gate=gate_payload,
        granularity=granularity,
    )


def trace_detour(
    thread_id: str,
    from_step: str,
    to_step: str,
    reason: str,
    data: Optional[Dict[str, Any]] = None,
    *,
    granularity: str = "logic",
) -> None:
    detour_payload = data.copy() if data else {}
    detour_payload.setdefault("reason", reason)
    detour_info = {
        "from_step": from_step,
        "to_step": to_step,
        "reason": reason,
    }
    emit(
        thread_id,
        "DETOUR",
        step=from_step,
        detail=f"{from_step}→{to_step}",
        data=detour_payload,
        subject=from_step,
        status="changed",
        detour_to_step=_step_number(to_step),
        owner_step=from_step,
        detour=detour_info,
        granularity=granularity,
    )


def trace_db_read(
    thread_id: str,
    owner_step: str,
    resource: str,
    data: Optional[Dict[str, Any]] = None,
    *,
    duration_ms: Optional[float] = None,
    granularity: str = "logic",
) -> None:
    db_info = {
        "op": resource,
        "mode": "READ",
    }
    if duration_ms is not None:
        db_info["duration_ms"] = duration_ms
    emit(
        thread_id,
        "DB_READ",
        step=owner_step,
        detail="READ",
        data=data or {},
        owner_step=owner_step,
        subject=resource,
        status="checked",
        db=db_info,
        granularity=granularity,
    )


def trace_db_write(
    thread_id: str,
    owner_step: str,
    resource: str,
    data: Optional[Dict[str, Any]] = None,
    *,
    duration_ms: Optional[float] = None,
    granularity: str = "logic",
) -> None:
    db_info = {
        "op": resource,
        "mode": "WRITE",
    }
    if duration_ms is not None:
        db_info["duration_ms"] = duration_ms
    emit(
        thread_id,
        "DB_WRITE",
        step=owner_step,
        detail="WRITE",
        data=data or {},
        owner_step=owner_step,
        subject=resource,
        status="changed",
        db=db_info,
        granularity=granularity,
    )


def trace_entity(
    thread_id: str,
    owner_step: str,
    name: str,
    source: str,
    accepted: bool,
    data: Optional[Dict[str, Any]] = None,
    status_override: Optional[str] = None,
    previous_value: Optional[Any] = None,
    *,
    granularity: str = "logic",
) -> None:
    lifecycle = status_override or ("captured" if accepted else "changed")
    entity_info: Dict[str, Any] = {
        "lifecycle": lifecycle,
        "key": name,
    }
    value = None
    if data and "value" in data:
        value = data.get("value")
    if value is not None:
        entity_info["value"] = value
    if previous_value is not None:
        entity_info["previous_value"] = previous_value
    emit(
        thread_id,
        "ENTITY_CAPTURE" if accepted else "ENTITY_SUPERSEDED",
        step=owner_step,
        detail=f"{name} ({source})",
        data=data or {},
        subject=name,
        status=lifecycle,
        owner_step=owner_step,
        entity=entity_info,
        granularity=granularity,
    )


def trace_draft(thread_id: str, owner_step: str, footer: Dict[str, Any], actions: Any) -> None:
    data = {"footer": footer, "actions": list(actions or [])}
    if is_trace_enabled():
        from backend.debug.state_store import STATE_STORE  # pylint: disable=import-outside-toplevel

        STATE_STORE.update(thread_id, {"step": step, **data})
    wait_state = footer.get("wait_state")
    draft_info = {"footer": {"step": footer.get("step"), "next": footer.get("next"), "state": wait_state}}
    emit(
        thread_id,
        "DRAFT_SEND",
        step=owner_step,
        data=data,
        subject=f"Draft {owner_step}",
        status="changed",
        wait_state=wait_state,
        owner_step=owner_step,
        draft=draft_info,
        granularity="logic",
    )


def trace_state(thread_id: str, step: str, snapshot: Dict[str, Any]) -> None:
    if is_trace_enabled():
        from backend.debug.state_store import STATE_STORE  # pylint: disable=import-outside-toplevel

        STATE_STORE.update(thread_id, snapshot)
    wait_state = snapshot.get("thread_state") or snapshot.get("threadState")
    payload = dict(snapshot)
    summary_hint = _state_summary(snapshot)
    if summary_hint:
        payload["summary"] = summary_hint
    emit(
        thread_id,
        "STATE_SNAPSHOT",
        step=step,
        data=payload,
        subject="state",
        status="changed",
        wait_state=wait_state if isinstance(wait_state, str) else None,
        owner_step=step,
        granularity="verbose",
    )


def trace_qa_enter(thread_id: str, detail: str, data: Optional[Dict[str, Any]] = None) -> None:
    emit(
        thread_id,
        "QA_ENTER",
        step="qna",
        detail=detail,
        data=data or {},
        subject="QA",
        status="checked",
        owner_step="qna",
        granularity="logic",
    )


def trace_qa_exit(thread_id: str, detail: str, data: Optional[Dict[str, Any]] = None) -> None:
    emit(
        thread_id,
        "QA_EXIT",
        step="qna",
        detail=detail,
        data=data or {},
        subject="QA",
        status="checked",
        owner_step="qna",
        granularity="logic",
    )


def trace_marker(
    thread_id: str,
    label: str,
    *,
    detail: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
    owner_step: Optional[str] = None,
    granularity: str = "verbose",
) -> None:
    """Emit a lightweight marker in the steps lane for notable internal actions."""

    owner = owner_step or label
    loop = _LAST_STEP.get(thread_id) == owner
    _LAST_STEP[thread_id] = owner
    emit(
        thread_id,
        "STEP_ENTER",
        step=owner,
        detail=detail,
        data=data or {},
        subject=label,
        status="checked",
        loop=loop,
        owner_step=owner,
        granularity=granularity,
    )


__all__ = [
    "trace_step",
    "trace_gate",
    "trace_detour",
    "trace_db_read",
    "trace_db_write",
    "trace_entity",
    "trace_draft",
    "trace_state",
    "trace_qa_enter",
    "trace_qa_exit",
    "trace_marker",
]


def _step_number(step_label: str) -> Optional[int]:
    if not step_label:
        return None
    for token in step_label.split("_"):
        if token.isdigit():
            try:
                return int(token)
            except ValueError:
                continue
    try:
        if step_label.startswith("Step"):
            return int("".join(ch for ch in step_label if ch.isdigit()))
    except ValueError:
        return None
    return None


def _state_summary(snapshot: Dict[str, Any]) -> Optional[str]:
    pieces = []
    thread_state = snapshot.get("thread_state") or snapshot.get("threadState")
    if thread_state:
        pieces.append(f"state={thread_state}")
    step = snapshot.get("step") or snapshot.get("current_step")
    if step:
        pieces.append(f"step={step}")
    if snapshot.get("date_confirmed") is True:
        pieces.append("date=confirmed")
    if snapshot.get("locked_room_id"):
        pieces.append(f"room={snapshot.get('locked_room_id')}")
    if not pieces:
        return None
    return " · ".join(pieces[:3])
