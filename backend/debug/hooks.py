from __future__ import annotations

from functools import wraps
from typing import Any, Callable, Dict, Optional, Tuple

from .settings import is_trace_enabled
from .trace import emit

_LAST_STEP: Dict[str, str] = {}
_LAST_GATE: Dict[str, Tuple[str, bool]] = {}


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
                subject=step_name,
                status="checked",
                loop=loop,
            )
            try:
                return fn(*args, **kwargs)
            finally:
                emit(
                    thread_id,
                    "STEP_EXIT",
                    step=step_name,
                    subject=step_name,
                    status="checked",
                )

        return inner

    return deco


def trace_gate(thread_id: str, step: str, gate_label: str, ok: bool, data: Optional[Dict[str, Any]] = None) -> None:
    previous = _LAST_GATE.get(thread_id)
    loop = bool(previous and previous[0] == gate_label)
    _LAST_GATE[thread_id] = (gate_label, ok)
    emit(
        thread_id,
        "GATE_PASS" if ok else "GATE_FAIL",
        step=step,
        detail=gate_label,
        data=data or {},
        subject=gate_label,
        status="pass" if ok else "fail",
        loop=loop,
    )


def trace_detour(thread_id: str, from_step: str, to_step: str, reason: str, data: Optional[Dict[str, Any]] = None) -> None:
    detour_payload = data or {}
    detour_payload.setdefault("reason", reason)
    emit(
        thread_id,
        "DETOUR",
        step=from_step,
        detail=f"{from_step}→{to_step}",
        data=detour_payload,
        subject=from_step,
        status="changed",
        detour_to_step=_step_number(to_step),
    )


def trace_db_read(thread_id: str, resource: str, data: Optional[Dict[str, Any]] = None) -> None:
    emit(
        thread_id,
        "DB_READ",
        step=resource,
        detail="READ",
        data=data or {},
        subject=resource,
        status="checked",
    )


def trace_db_write(thread_id: str, resource: str, data: Optional[Dict[str, Any]] = None) -> None:
    emit(
        thread_id,
        "DB_WRITE",
        step=resource,
        detail="WRITE",
        data=data or {},
        subject=resource,
        status="changed",
    )


def trace_entity(
    thread_id: str,
    name: str,
    source: str,
    accepted: bool,
    data: Optional[Dict[str, Any]] = None,
    status_override: Optional[str] = None,
) -> None:
    emit(
        thread_id,
        "ENTITY_CAPTURE" if accepted else "ENTITY_SUPERSEDED",
        step="Step1_Intake",
        detail=f"{name} ({source})",
        data=data or {},
        subject=name,
        status=status_override or ("captured" if accepted else "changed"),
    )


def trace_draft(thread_id: str, step: str, footer: Dict[str, Any], actions: Any) -> None:
    data = {"footer": footer, "actions": list(actions or [])}
    if is_trace_enabled():
        from backend.debug.state_store import STATE_STORE  # pylint: disable=import-outside-toplevel

        STATE_STORE.update(thread_id, {"step": step, **data})
    wait_state = footer.get("wait_state")
    emit(
        thread_id,
        "DRAFT_SEND",
        step=step,
        data=data,
        subject=f"Draft {step}",
        status="changed",
        wait_state=wait_state,
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
    )


def trace_marker(thread_id: str, label: str, *, detail: Optional[str] = None, data: Optional[Dict[str, Any]] = None) -> None:
    """Emit a lightweight marker in the steps lane for notable internal actions."""

    loop = _LAST_STEP.get(thread_id) == label
    _LAST_STEP[thread_id] = label
    emit(
        thread_id,
        "STEP_ENTER",
        step=label,
        detail=detail,
        data=data or {},
        subject=label,
        status="checked",
        loop=loop,
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
