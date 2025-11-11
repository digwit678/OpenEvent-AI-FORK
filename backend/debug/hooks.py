from __future__ import annotations

import re
from functools import wraps
import inspect
from typing import Any, Callable, Dict, List, Optional, Tuple

try:  # pragma: no cover - debugger counters are optional in some environments
    from backend.workflows.debugger.counters import compute_step_counters  # type: ignore[import]
except Exception:  # pragma: no cover - fallback when workflows package unavailable
    compute_step_counters = None  # type: ignore[assignment]

from .settings import is_trace_enabled
from .trace import (
    REQUIREMENTS_MATCH_HELP,
    clear_subloop_context,
    emit,
    get_subloop_context,
    has_open_hil,
    set_hil_open,
    set_subloop_context,
)

_LAST_STEP: Dict[str, str] = {}
_LAST_GATE: Dict[str, Tuple[str, bool]] = {}
_GATE_STATE: Dict[Tuple[str, str], Dict[str, bool]] = {}
_CONFIRMED_VALUES: Dict[str, Dict[str, str]] = {}

_IMMEDIATE_CONFIRM = {"email"}
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\+?\d[\d\s\-]{6,}")


def _callsite_path(skip: int = 2) -> Optional[str]:
    frame = inspect.currentframe()
    try:
        for _ in range(skip):
            if frame is None:
                return None
            frame = frame.f_back
        if frame is None:
            return None
        module = inspect.getmodule(frame)
        module_name = module.__name__ if module else None
        code = frame.f_code
        qualname = getattr(code, "co_qualname", None)
        if not qualname:
            qualname = code.co_name
            owner = frame.f_locals.get("self")
            if owner is not None:
                try:
                    qualname = f"{owner.__class__.__name__}.{qualname}"
                except Exception:
                    pass
            else:
                cls = frame.f_locals.get("cls")
                if isinstance(cls, type):
                    qualname = f"{cls.__name__}.{qualname}"
        if module_name and qualname:
            return f"{module_name}.{qualname}"
        return module_name or qualname
    finally:
        del frame


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


def _normalised_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _room_status_display(snapshot: Dict[str, Any]) -> Optional[str]:
    locked_room = snapshot.get("locked_room_id") or snapshot.get("selected_room")
    if not locked_room:
        return "Unselected"
    status = (
        snapshot.get("locked_room_status")
        or snapshot.get("selected_status")
        or snapshot.get("room_status")
    )
    status_text = _normalised_str(status)
    if status_text:
        lowered = status_text.lower()
        if "available" in lowered:
            return "Available"
        if "option" in lowered:
            return "Option"
        if "unavailable" in lowered:
            return "Unavailable"
        return status_text
    return "Available"


def _offer_status_display(status: Optional[str], hil_open: bool) -> str:
    status_text = _normalised_str(status)
    if not status_text:
        return "—"
    lowered = status_text.lower()
    if lowered == "accepted":
        return "Confirmed by HIL"
    if hil_open:
        return "Waiting on HIL"
    if lowered == "declined":
        return "Declined"
    if lowered in {"draft", "drafting", "in creation"}:
        return "In creation"
    return status_text


def _tracked_info(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    info: Dict[str, Any] = {}
    event_data = snapshot.get("event_data") or {}
    billing_details = snapshot.get("billing_details") or {}
    if not isinstance(billing_details, dict):
        billing_details = {}
    billing_raw = None
    if isinstance(event_data, dict):
        billing_raw = event_data.get("Billing Address") or event_data.get("billing_address")
    if isinstance(billing_details, dict):
        structured = {
            key: value
            for key, value in billing_details.items()
            if key != "raw" and _normalised_str(value)
        }
        if structured:
            info["billing_address_saved"] = True
            return info
    raw_text = _normalised_str(billing_raw)
    if raw_text:
        info["billing_address_captured_raw"] = raw_text
    return info


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
    callsite = _callsite_path()
    detail_payload: Dict[str, Any] = {"fn": callsite or fn_name, "label": fn_name, "kind": "instruction"}
    if callsite:
        detail_payload["path"] = callsite
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
        details_label=callsite or fn_name,
        detail=detail_payload,
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
    callsite = _callsite_path()
    detail_payload: Dict[str, Any] = {"fn": callsite or fn_name, "label": fn_name, "kind": "reply"}
    if callsite:
        detail_payload["path"] = callsite
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
        details_label=callsite or fn_name,
        detail=detail_payload,
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
        fn_path = f"{fn.__module__}.{fn.__qualname__}"
        detail_payload = {"fn": fn_path, "label": step_name}
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
                detail=detail_payload,
                details_label=fn_path,
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
                    detail=detail_payload,
                    details_label=fn_path,
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
    subloop: Optional[str] = None,
) -> None:
    if subloop:
        set_subloop_context(thread_id, subloop)
    current_subloop = subloop or get_subloop_context(thread_id)

    data = {"footer": footer, "actions": list(actions or [])}
    if prompt is not None:
        data["prompt"] = prompt
    if current_subloop:
        data["subloop"] = current_subloop
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
    provided_subloop = _normalised_str(payload.get("subloop"))
    if provided_subloop:
        set_subloop_context(thread_id, provided_subloop)
    current_subloop = get_subloop_context(thread_id)
    if current_subloop:
        payload["subloop"] = current_subloop

    if flags:
        payload["flags"] = flags
    payload.setdefault("hil_open", bool(hil_flag))
    set_hil_open(thread_id, bool(payload.get("hil_open")))

    locked_room = payload.get("locked_room_id") or payload.get("selected_room")
    room_selected = bool(_normalised_str(locked_room))
    payload.setdefault("room_selected", room_selected)

    req_hash = payload.get("requirements_hash") or payload.get("req_hash")
    eval_hash = payload.get("room_eval_hash") or payload.get("eval_hash")
    req_hash_normalized = _normalised_str(req_hash)
    eval_hash_normalized = _normalised_str(eval_hash)
    requirements_match = bool(room_selected and req_hash_normalized and eval_hash_normalized and req_hash_normalized == eval_hash_normalized)
    payload["requirements_match"] = requirements_match
    payload["requirements_match_tooltip"] = REQUIREMENTS_MATCH_HELP

    room_status_display = _room_status_display(payload)
    if room_status_display:
        payload["room_status_display"] = room_status_display
        payload["room_status"] = room_status_display

    hil_open_flag = bool(payload.get("hil_open"))
    payload["offer_status_display"] = _offer_status_display(payload.get("offer_status"), hil_open_flag)

    tracked = _tracked_info(payload)
    if tracked:
        payload["tracked_info"] = tracked

    counters: Optional[Dict[str, Any]] = None

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

        if compute_step_counters:
            try:
                counters = compute_step_counters(merged)
            except Exception:  # pragma: no cover - defensive fallback
                counters = None
        if counters:
            merged["step_counters"] = counters
            payload["step_counters"] = counters

        STATE_STORE.update(thread_id, merged)
    else:
        if compute_step_counters:
            try:
                counters = compute_step_counters(payload)
            except Exception:  # pragma: no cover - defensive fallback
                counters = None
        if counters:
            payload["step_counters"] = counters
    wait_state = snapshot.get("thread_state") or snapshot.get("threadState")
    summary_hint = _state_summary(snapshot)
    if summary_hint:
        payload["summary"] = summary_hint
    hash_status = None
    if req_hash_normalized and eval_hash_normalized:
        hash_status = "Match" if requirements_match else "Mismatch"
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
        hash_help=REQUIREMENTS_MATCH_HELP if hash_status else None,
    )


def trace_qa_enter(thread_id: str, detail: str, data: Optional[Dict[str, Any]] = None) -> None:
    set_subloop_context(thread_id, "general_q_a")
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
    clear_subloop_context(thread_id)


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


def set_subloop(thread_id: str, subloop: Optional[str]) -> None:
    set_subloop_context(thread_id, subloop)


def clear_subloop(thread_id: str) -> None:
    clear_subloop_context(thread_id)


def current_subloop(thread_id: str) -> Optional[str]:
    return get_subloop_context(thread_id)


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
    "set_subloop",
    "clear_subloop",
    "current_subloop",
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
