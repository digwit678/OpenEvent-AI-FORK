from __future__ import annotations

import re
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Tuple

from .settings import is_trace_enabled
from .trace import emit, set_hil_open, has_open_hil

_LAST_STEP: Dict[str, str] = {}
_LAST_GATE: Dict[str, Tuple[str, bool]] = {}
_GATE_STATE: Dict[Tuple[str, str], Dict[str, bool]] = {}
_CONFIRMED_VALUES: Dict[str, Dict[str, str]] = {}

_IMMEDIATE_CONFIRM = {"email"}
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\+?\d[\d\s\-]{6,}")


def _format_chip(key: str, value: Any) -> str:
    return f"{key}={value}"


def _normalise_gate_label(label: str) -> str:
    if not label:
        return "requirement"
    parts = label.split(" ", 1)
    core = parts[1] if (parts and parts[0].upper().startswith("P") and len(parts[0]) == 2) else label
    cleaned = (
        core.replace("→", " ")
        .replace("-", " ")
        .replace(".", " ")
        .replace("/", " ")
        .strip()
    )
    return "_".join(segment for segment in cleaned.lower().split() if segment) or "requirement"


def _register_gate_state(thread_id: str, owner_step: str, gate_label: str, passed: bool) -> Dict[str, Any]:
    key = _normalise_gate_label(gate_label)
    state = _GATE_STATE.setdefault((thread_id, owner_step), {})
    state[key] = passed
    met = sum(1 for ok in state.values() if ok)
    required = len(state)
    missing = [label for label, ok in state.items() if not ok]
    return {
        "label": gate_label,
        "met": met,
        "required": required,
        "missing": missing,
        "result": "PASS" if passed else "FAIL",
    }


def _register_confirmed(thread_id: str, key: str, value: Optional[Any]) -> Optional[str]:
    if value in (None, ""):
        return None
    store = _CONFIRMED_VALUES.setdefault(thread_id, {})
    chip = _format_chip(key, value)
    if store.get(key) == str(value):
        return None
    store[key] = str(value)
    return chip


def _io_result_from_payload(payload: Optional[Dict[str, Any]]) -> Optional[str]:
    if not payload:
        return None
    if "result" in payload and isinstance(payload["result"], str):
        return payload["result"]
    if "count" in payload and isinstance(payload["count"], int):
        return f"{payload['count']} available"
    if "rooms" in payload and isinstance(payload["rooms"], list):
        return f"{len(payload['rooms'])} available"
    if "updated" in payload:
        updated = payload.get("updated")
        if isinstance(updated, list):
            return f"updated {len(updated)}"
        return "ok"
    if "event_id" in payload:
        return "ok"
    return None


def _mask_prompt(text: Optional[str]) -> Optional[str]:
    if not text:
        return None

    def _email_repl(match: re.Match[str]) -> str:
        email = match.group(0)
        if "@" not in email:
            return "***@***"
        local, domain = email.split("@", 1)
        if not local:
            return f"***@{domain}"
        prefix = local[0]
        return f"{prefix}***@{domain}"

    masked = _EMAIL_RE.sub(_email_repl, text)
    masked = _PHONE_RE.sub("[redacted-number]", masked)
    collapsed = re.sub(r"\s+", " ", masked).strip()
    return collapsed


def _marker_semantics(label: str) -> Tuple[str, str, str]:
    upper = label.upper() if label else ""
    if upper.startswith("TRIGGER"):
        return ("Trigger", "Client", "Captured")
    if upper.startswith("AGENT"):
        return ("Agent", "Agent", "Checked")
    if upper.startswith("HIL"):
        return ("HIL", "HIL", "Checked")
    if upper.startswith("CONDITIONAL"):
        return ("Condition", "System", "Checked")
    if upper.startswith("DB"):
        return ("DB Action", "System", "Queried")
    return ("Condition", "System", "Checked")


def _prompt_preview(text: str, limit: int = 180) -> Optional[str]:
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def trace_prompt_in(
    thread_id: str,
    owner_step: str,
    fn_name: str,
    prompt_text: Optional[str],
    *,
    actor: str = "Agent",
    granularity: str = "logic",
) -> None:
    sanitized = _mask_prompt(prompt_text) or ""
    payload = {"prompt_text": sanitized}
    emit(
        thread_id,
        "AGENT_PROMPT_IN",
        step=owner_step,
        owner_step=owner_step,
        subject=fn_name,
        status="sent",
        granularity=granularity,
        entity_label="Agent",
        actor=actor,
        event_name="Instruction",
        details_label=fn_name,
        detail={"fn": fn_name, "kind": "instruction"},
        data=payload,
        prompt_preview=_prompt_preview(sanitized),
    )


def trace_prompt_out(
    thread_id: str,
    owner_step: str,
    fn_name: str,
    message_text: Optional[str],
    *,
    actor: str = "Agent",
    outputs: Optional[Dict[str, Any]] = None,
    granularity: str = "logic",
) -> None:
    sanitized = _mask_prompt(message_text) or ""
    payload: Dict[str, Any] = {"message_text": sanitized}
    if outputs:
        payload["outputs"] = outputs
    emit(
        thread_id,
        "AGENT_PROMPT_OUT",
        step=owner_step,
        owner_step=owner_step,
        subject=fn_name,
        status="completed",
        granularity=granularity,
        entity_label="Agent",
        actor=actor,
        event_name="Reply",
        details_label=fn_name,
        detail={"fn": fn_name, "kind": "reply"},
        data=payload,
        prompt_preview=_prompt_preview(sanitized),
    )


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
                entity_label="Trigger",
                actor="System",
                event_name="Enter",
                details_label=step_name,
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
                    entity_label="Trigger",
                    actor="System",
                    event_name="Exit",
                    details_label=step_name,
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
    gate_payload = _register_gate_state(thread_id, owner_step, gate_label, ok)
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
        entity_label="Condition",
        actor="System",
        event_name="Checked",
        details_label=gate_label,
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
        entity_label="Detour",
        actor="System",
        event_name="Routed",
        details_label=f"{from_step}→{to_step}",
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
    io_payload = {
        "direction": "READ",
        "op": resource,
    }
    result = _io_result_from_payload(data)
    if result:
        io_payload["result"] = result
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
        entity_label="DB Action",
        actor="System",
        event_name="Queried",
        details_label=resource,
        io=io_payload,
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
    io_payload = {
        "direction": "WRITE",
        "op": resource,
    }
    result = _io_result_from_payload(data)
    if result:
        io_payload["result"] = result
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
        entity_label="DB Action",
        actor="System",
        event_name="Updated",
        details_label=resource,
        io=io_payload,
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
    captured_chips: List[str] = []
    confirmed_chips: List[str] = []
    value_repr = entity_info.get("value")
    value_text = str(value_repr) if value_repr is not None else None
    if accepted and value_text is not None:
        captured_chips.append(_format_chip(name, value_text))
    should_confirm = status_override == "confirmed" or name in _IMMEDIATE_CONFIRM
    if should_confirm and value_text is not None:
        confirmed_chip = _register_confirmed(thread_id, name, value_text)
        if confirmed_chip:
            confirmed_chips.append(confirmed_chip)
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
        entity_label="Agent",
        actor="Agent",
        event_name="Captured" if accepted else "Checked",
        details_label=source,
        captured_additions=captured_chips,
        confirmed_now=confirmed_chips,
    )


def trace_draft(
    thread_id: str,
    owner_step: str,
    footer: Dict[str, Any],
    actions: Any,
    prompt: Optional[str] = None,
) -> None:
    data = {"footer": footer, "actions": list(actions or [])}
    if prompt is not None:
        data["prompt"] = prompt
    if is_trace_enabled():
        from backend.debug.state_store import STATE_STORE  # pylint: disable=import-outside-toplevel

        current = STATE_STORE.get(thread_id)
        merged_state = dict(current)
        merged_state.update({"step": owner_step, **data})
        STATE_STORE.update(thread_id, merged_state)
    wait_state = footer.get("wait_state")
    draft_info = {"footer": {"step": footer.get("step"), "next": footer.get("next"), "state": wait_state}}
    preview_source = _mask_prompt(prompt)
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
        entity_label="Draft",
        actor="Agent",
        event_name="Draft Sent",
        details_label=owner_step,
        prompt_preview=_prompt_preview(preview_source or ""),
    )


def _state_flags(step: str, snapshot: Dict[str, Any]) -> Dict[str, bool]:
    flags: Dict[str, bool] = {}
    step_lower = (step or "").lower()
    if step_lower.startswith("step1"):
        intent_value = snapshot.get("intent") or snapshot.get("intent_label") or snapshot.get("detected_intent")
        participants_value = (
            snapshot.get("participants")
            or snapshot.get("number_of_participants")
            or snapshot.get("participants_captured")
        )
        participants_ok = False
        if isinstance(participants_value, (int, float)):
            participants_ok = participants_value > 0
        else:
            participants_ok = bool(participants_value)
        email_value = snapshot.get("contact_email") or snapshot.get("email") or snapshot.get("client_email")
        flags.update(
            {
                "intentDetected": bool(intent_value),
                "participants": participants_ok,
                "emailConfirmed": bool(email_value),
            }
        )
    elif step_lower.startswith("step2"):
        date_candidate = (
            snapshot.get("chosen_date")
            or snapshot.get("event_date")
            or snapshot.get("candidate_date")
            or snapshot.get("date")
        )
        flags.update(
            {
                "dateCaptured": bool(date_candidate),
                "dateConfirmed": bool(snapshot.get("date_confirmed")),
            }
        )
    return flags


def trace_state(thread_id: str, step: str, snapshot: Dict[str, Any]) -> None:
    flags = _state_flags(step, snapshot)
    hil_flag = snapshot.get("hil_open")
    if isinstance(hil_flag, bool):
        set_hil_open(thread_id, hil_flag)
    elif has_open_hil(thread_id):
        hil_flag = True
    else:
        hil_flag = False

    payload = dict(snapshot)
    if flags:
        payload["flags"] = flags
    payload.setdefault("hil_open", bool(hil_flag))
    set_hil_open(thread_id, bool(payload.get("hil_open")))

    if is_trace_enabled():
        from backend.debug.state_store import STATE_STORE  # pylint: disable=import-outside-toplevel

        current = STATE_STORE.get(thread_id)
        merged = dict(current)
        merged.update(payload)
        if flags:
            merged_flags = dict(current.get("flags") or {})
            merged_flags.update(flags)
            merged["flags"] = merged_flags
        merged["hil_open"] = bool(payload.get("hil_open"))
        STATE_STORE.update(thread_id, merged)
    wait_state = snapshot.get("thread_state") or snapshot.get("threadState")
    summary_hint = _state_summary(snapshot)
    if summary_hint:
        payload["summary"] = summary_hint
    requirements_hash = snapshot.get("requirements_hash")
    room_hash = snapshot.get("room_eval_hash")
    hash_status = None
    if requirements_hash or room_hash:
        if requirements_hash and room_hash and requirements_hash == room_hash:
            hash_status = "Match"
        elif requirements_hash and room_hash:
            hash_status = "Mismatch"
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
        entity_label="Waiting" if wait_state else None,
        actor="System",
        event_name="State Snapshot",
        details_label="state.update",
        hash_status=hash_status,
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
        entity_label="Q&A",
        actor="Agent",
        event_name="Enter",
        details_label=detail,
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
        entity_label="Q&A",
        actor="Agent",
        event_name="Exit",
        details_label=detail,
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
    entity_label, actor, event_name = _marker_semantics(label)
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
        entity_label=entity_label,
        actor=actor,
        event_name=event_name,
        details_label=detail or label,
    )


__all__ = [
    "trace_step",
    "trace_gate",
    "trace_detour",
    "trace_db_read",
    "trace_db_write",
    "trace_entity",
    "trace_draft",
    "trace_prompt_in",
    "trace_prompt_out",
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
