from __future__ import annotations

import copy
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import re

from backend.workflows.common.datetime_parse import to_iso_date
from backend.workflows.common.room_rules import find_better_room_dates
from backend.workflows.common.timeutils import format_iso_date_to_ddmmyyyy
from backend.workflows.common.capture import capture_user_fields
from backend.domain import IntentLabel
from backend.workflows.common.gatekeeper import refresh_gatekeeper
from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflows.io.database import append_audit_entry, load_rooms, update_event_metadata
from backend.utils.profiler import profile_step
from backend.config.flags import env_flag

from ..condition.decide import room_status_on_date
from ..llm.analysis import summarize_room_statuses

__workflow_role__ = "trigger"


ROOM_OUTCOME_UNAVAILABLE = "Unavailable"
ROOM_OUTCOME_AVAILABLE = "Available"
ROOM_OUTCOME_OPTION = "Option"

ROOM_SIZE_ORDER = {
    "Room A": 1,
    "Room B": 2,
    "Room C": 3,
    "Punkt.Null": 4,
}

ROOM_CACHE_TTL_MINUTES = 10

_LOCK_KEYWORD_PATTERN = re.compile(r"\b(lock|reserve|hold|secure|keep|confirm|book|take)\b", re.IGNORECASE)


def _auto_lock_min_confidence() -> float:
    raw = os.getenv("AUTO_LOCK_MIN_CONFIDENCE", "0.85")
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return 0.85


def _utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


@profile_step("workflow.step3.room_availability")
def process(state: WorkflowState) -> GroupResult:
    """[Trigger] Execute Group C — room availability assessment with entry guards and caching."""

    AUTO_LOCK = env_flag("ALLOW_AUTO_ROOM_LOCK", False)
    event_entry = state.event_entry
    if not event_entry:
        payload = {
            "client_id": state.client_id,
            "event_id": state.event_id,
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "reason": "missing_event_record",
            "context": state.context_snapshot,
        }
        return GroupResult(action="room_eval_missing_event", payload=payload, halt=True)

    if not state.user_info.get("hil_approve_step") and _locked_room_still_valid(event_entry):
        return _reuse_locked_room(state, event_entry)

    state.current_step = 3
    capture_user_fields(state, current_step=3, source=state.message.msg_id)

    hil_step = state.user_info.get("hil_approve_step")
    if hil_step == 3:
        decision = state.user_info.get("hil_decision") or "approve"
        return _apply_hil_decision(state, event_entry, decision)

    chosen_date = event_entry.get("chosen_date")
    if not chosen_date:
        return _detour_to_date(state, event_entry)

    requested_window = event_entry.get("requested_window") or {}
    window_hash = requested_window.get("hash")

    user_requested_room = state.user_info.get("room")
    locked_room_id = event_entry.get("locked_room_id")
    current_req_hash = event_entry.get("requirements_hash")
    room_eval_hash = event_entry.get("room_eval_hash")

    delta_query_iso = state.extras.pop("delta_date_query", None)
    if delta_query_iso:
        baseline_display = requested_window.get("display_date") or event_entry.get("chosen_date")
        baseline_iso = requested_window.get("date_iso") or (to_iso_date(baseline_display) if baseline_display else None)
        if baseline_iso and delta_query_iso != baseline_iso:
            return _handle_delta_availability(
                state,
                event_entry,
                delta_query_iso,
                requested_window,
                baseline_iso,
                baseline_display,
            )

    requirements_changed = bool(current_req_hash and current_req_hash != room_eval_hash)
    explicit_room_change = bool(user_requested_room and user_requested_room != locked_room_id)
    missing_lock = locked_room_id is None
    cache_payload = event_entry.get("room_eval_cache") or {}

    cached_result = _maybe_use_cached_eval(
        state,
        event_entry,
        cache_payload,
        window_hash,
        current_req_hash,
        requirements_changed,
        explicit_room_change,
    )
    if cached_result is not None:
        return cached_result

    if not (missing_lock or explicit_room_change or requirements_changed):
        return _skip_room_evaluation(state, event_entry)

    room_statuses = evaluate_room_statuses(state.db, chosen_date)
    summary = summarize_room_statuses(room_statuses)
    status_map = _flatten_statuses(room_statuses)

    preferred_room = _preferred_room(event_entry, user_requested_room)
    selected_room, selected_status = _select_room(preferred_room, status_map)
    requirements = event_entry.get("requirements") or {}

    outcome = selected_status or ROOM_OUTCOME_UNAVAILABLE
    auto_lock_score = _auto_lock_confidence(status_map, selected_room, outcome)
    intent_label = state.intent or IntentLabel.EVENT_REQUEST
    if isinstance(intent_label, str):
        try:
            intent_label = IntentLabel(intent_label)
        except ValueError:
            intent_label = IntentLabel.NON_EVENT
    intent_value = intent_label.value if isinstance(intent_label, IntentLabel) else str(intent_label).lower()
    requested_room_id = user_requested_room or ""
    explicit_room = _canonical_room_name(requested_room_id, status_map)
    text_room, keyword_found = _detect_textual_room_request(state.message, status_map)
    if text_room:
        explicit_room = text_room
    explicit_from_intent = isinstance(intent_label, IntentLabel) and intent_label == IntentLabel.EDIT_ROOM
    user_explicit_room = bool(explicit_room) and (keyword_found or explicit_from_intent)
    if keyword_found and not explicit_room:
        _record_lock_attempt(
            state,
            allowed=False,
            policy=AUTO_LOCK,
            intent=intent_value,
            selected_room=None,
            path="room_availability.process",
            reason="room_not_recognized",
        )

    existing_lock = event_entry.get("locked_room_id")
    explicit_status = status_map.get(explicit_room) if explicit_room else None
    if user_explicit_room and explicit_room and explicit_status == ROOM_OUTCOME_AVAILABLE:
        same_room = _same_room(existing_lock, explicit_room)
        return _finalize_room_lock(
            state,
            event_entry,
            explicit_room,
            chosen_date,
            requirements,
            room_statuses,
            summary,
            current_req_hash,
            reason="user_explicit",
            audit_reason="room_user_locked" if not same_room else "room_lock_retained",
            action="room_auto_locked" if not same_room else "room_lock_retained",
            final_action="room_auto_locked" if not same_room else "room_lock_retained",
            auto_payload=False,
            policy_flag=AUTO_LOCK,
        )

    if user_explicit_room and explicit_room and explicit_status != ROOM_OUTCOME_AVAILABLE:
        _record_lock_attempt(
            state,
            allowed=False,
            policy=AUTO_LOCK,
            intent=intent_value,
            selected_room=explicit_room,
            path="room_availability.process",
            reason=f"room_status_{explicit_status or 'unknown'}",
        )

    if user_explicit_room and explicit_room:
        autolock_meta = state.telemetry.setdefault("autolock", {})
        autolock_meta["considered"] = True
        autolock_meta["allowed"] = AUTO_LOCK
        autolock_meta["explicit"] = True
        autolock_meta["skipped"] = True
        autolock_meta["status"] = explicit_status or "unknown"
        if "room_selection" not in state.telemetry.deferred_intents:
            state.telemetry.deferred_intents.append("room_selection")

    auto_lock_candidate = (
        selected_room
        and outcome == ROOM_OUTCOME_AVAILABLE
        and auto_lock_score >= _auto_lock_min_confidence()
    )
    if auto_lock_candidate and AUTO_LOCK:
        return _finalize_room_lock(
            state,
            event_entry,
            selected_room,
            chosen_date,
            requirements,
            room_statuses,
            summary,
            current_req_hash,
            reason="auto_policy",
            audit_reason="room_auto_locked",
            action="room_auto_locked",
            final_action="room_auto_locked",
            auto_payload=True,
            policy_flag=AUTO_LOCK,
        )

    if auto_lock_candidate:
        autolock_meta = state.telemetry.setdefault("autolock", {})
        autolock_meta["considered"] = True
        autolock_meta["allowed"] = AUTO_LOCK
        autolock_meta["explicit"] = False
        autolock_meta["skipped"] = True
        if "room_selection" not in state.telemetry.deferred_intents:
            state.telemetry.deferred_intents.append("room_selection")
        _record_lock_attempt(
            state,
            allowed=False,
            policy=AUTO_LOCK,
            intent=intent_value,
            selected_room=selected_room,
            path="room_availability.process",
            reason="blocked_by_policy_no_explicit_selection",
        )

    draft_text = _compose_outcome_message(
        status_map,
        outcome,
        selected_room,
        chosen_date,
        requirements,
        preferred_room,
    )

    alt_dates: List[str] = []
    if _needs_better_room_alternatives(state.user_info, status_map, event_entry):
        alt_dates = find_better_room_dates(event_entry)
        if alt_dates:
            draft_text = _append_alt_dates(draft_text, alt_dates)

    outcome_topic = {
        ROOM_OUTCOME_AVAILABLE: "room_available",
        ROOM_OUTCOME_OPTION: "room_option",
        ROOM_OUTCOME_UNAVAILABLE: "room_unavailable",
    }[outcome]

    draft_message = {
        "body": draft_text,
        "step": 3,
        "topic": outcome_topic,
        "room": selected_room,
        "status": outcome,
    }
    if alt_dates:
        draft_message["alt_dates_for_better_room"] = alt_dates
    state.add_draft_message(draft_message)

    event_entry["room_pending_decision"] = {
        "selected_room": selected_room,
        "selected_status": outcome,
        "requirements_hash": current_req_hash,
        "summary": summary,
    }
    event_entry["room_decision"] = {
        "status": outcome.lower(),
        "reason": "awaiting_confirmation",
        "evaluated_at": _utc_now(),
    }
    event_entry["room_eval_cache"] = _build_cache_payload(
        draft_message,
        event_entry["room_pending_decision"],
        window_hash,
        current_req_hash,
    )

    update_event_metadata(
        event_entry,
        thread_state="Awaiting Client Response",
        current_step=3,
    )

    state.set_thread_state("Awaiting Client Response")
    state.caller_step = event_entry.get("caller_step")
    state.current_step = 3
    state.extras["persist"] = True

    payload = {
        "client_id": state.client_id,
        "event_id": state.event_id,
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "rooms": room_statuses,
        "summary": summary,
        "selected_room": selected_room,
        "selected_status": outcome,
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
    }
    if alt_dates:
        payload["alt_dates_for_better_room"] = alt_dates
    gatekeeper = refresh_gatekeeper(event_entry)
    payload["answered_question_first"] = True
    payload["delta_availability_used"] = False
    payload["gatekeeper_passed"] = dict(gatekeeper)
    state.telemetry.answered_question_first = True
    state.telemetry.delta_availability_used = False
    state.telemetry.gatekeeper_passed = dict(gatekeeper)
    return GroupResult(action="room_avail_result", payload=payload, halt=True)


def _maybe_use_cached_eval(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    cache_payload: Dict[str, Any],
    window_hash: Optional[str],
    current_req_hash: Optional[str],
    requirements_changed: bool,
    explicit_room_change: bool,
) -> Optional[GroupResult]:
    if not cache_payload or not window_hash or not current_req_hash:
        return None
    if requirements_changed or explicit_room_change:
        return None
    if cache_payload.get("window_hash") != window_hash:
        return None
    if cache_payload.get("requirements_hash") != current_req_hash:
        return None
    if not _cache_valid(cache_payload.get("expires_at")):
        return None
    return _reuse_cached_room_eval(state, event_entry, cache_payload)


def _reuse_cached_room_eval(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    cache_payload: Dict[str, Any],
) -> Optional[GroupResult]:
    draft = cache_payload.get("draft_message")
    if not draft:
        return None
    state.add_draft_message(copy.deepcopy(draft))

    pending = cache_payload.get("pending_decision")
    if pending:
        event_entry["room_pending_decision"] = copy.deepcopy(pending)

    update_event_metadata(
        event_entry,
        thread_state="Awaiting Client Response",
        current_step=3,
    )

    state.set_thread_state("Awaiting Client Response")
    state.caller_step = event_entry.get("caller_step")
    state.current_step = 3
    state.extras["persist"] = True

    payload: Dict[str, Any] = {
        "client_id": state.client_id,
        "event_id": state.event_id,
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "cached": True,
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
    }
    if pending:
        payload["selected_room"] = pending.get("selected_room")
        payload["selected_status"] = pending.get("selected_status")
        if pending.get("summary"):
            payload["summary"] = pending.get("summary")
    gatekeeper = refresh_gatekeeper(event_entry)
    payload["gatekeeper_passed"] = dict(gatekeeper)
    state.telemetry.answered_question_first = True
    state.telemetry.delta_availability_used = False
    state.telemetry.gatekeeper_passed = dict(gatekeeper)
    return GroupResult(action="room_eval_cached", payload=payload, halt=True)


def _build_cache_payload(
    draft_message: Dict[str, Any],
    pending_decision: Optional[Dict[str, Any]],
    window_hash: Optional[str],
    requirements_hash: Optional[str],
) -> Optional[Dict[str, Any]]:
    if not draft_message or not window_hash or not requirements_hash:
        return None
    payload: Dict[str, Any] = {
        "window_hash": window_hash,
        "requirements_hash": requirements_hash,
        "expires_at": _cache_expiry_iso(),
        "draft_message": copy.deepcopy(draft_message),
    }
    if pending_decision:
        payload["pending_decision"] = copy.deepcopy(pending_decision)
    return payload


def _cache_valid(expires_at: Optional[str]) -> bool:
    if not expires_at:
        return False
    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return datetime.utcnow() < expiry.replace(tzinfo=None)


def _cache_expiry_iso(minutes: int = ROOM_CACHE_TTL_MINUTES) -> str:
    expiry = datetime.utcnow() + timedelta(minutes=minutes)
    return expiry.replace(microsecond=0).isoformat() + "Z"


def _handle_delta_availability(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    new_date_iso: str,
    requested_window: Dict[str, Any],
    baseline_iso: str,
    baseline_display: Optional[str],
) -> GroupResult:
    baseline_display = (
        baseline_display
        or requested_window.get("display_date")
        or event_entry.get("chosen_date")
        or format_iso_date_to_ddmmyyyy(baseline_iso)
    )
    baseline_start = _normalize_time_label(requested_window.get("start_time"))
    baseline_end = _normalize_time_label(requested_window.get("end_time"))
    if not baseline_start or not baseline_end:
        event_data = event_entry.get("event_data") or {}
        baseline_start = baseline_start or _normalize_time_label(event_data.get("Start Time"))
        baseline_end = baseline_end or _normalize_time_label(event_data.get("End Time"))

    new_display = format_iso_date_to_ddmmyyyy(new_date_iso)
    query_start = _normalize_time_label(state.user_info.get("start_time")) or baseline_start
    query_end = _normalize_time_label(state.user_info.get("end_time")) or baseline_end

    rooms = load_rooms()
    baseline_map = {room: room_status_on_date(state.db, baseline_display, room) for room in rooms}
    new_map = {room: room_status_on_date(state.db, new_display, room) for room in rooms}

    diff_lines: List[str] = []
    all_rooms = sorted(set(baseline_map.keys()) | set(new_map.keys()), key=_room_rank)
    for room in all_rooms:
        prev_status = baseline_map.get(room, ROOM_OUTCOME_UNAVAILABLE)
        new_status = new_map.get(room, ROOM_OUTCOME_UNAVAILABLE)
        if new_status != prev_status:
            diff_lines.append(
                f"- {room}: now {new_status.lower()} (was {prev_status.lower()})"
            )
    if not diff_lines:
        diff_lines.append("No availability changes compared to the confirmed date.")

    price_line = "Price delta: none (rates unchanged)."
    baseline_room = event_entry.get("locked_room_id") or (event_entry.get("room_pending_decision") or {}).get("selected_room")
    if baseline_room:
        question_line = (
            f"Would you like to keep {baseline_display} in {baseline_room}, "
            f"switch to {new_display}, or explore another date?"
        )
    else:
        question_line = f"Should I keep {baseline_display} or switch to {new_display}? Happy to check another date as well."

    window_label = _format_time_range(query_start, query_end, baseline_start, baseline_end)
    if window_label:
        header = f"For {new_display} ({window_label}) vs {baseline_display}, here's what changed:"
    else:
        header = f"For {new_display} vs {baseline_display}, here's what changed:"

    lines = [header]
    lines.extend(diff_lines)
    lines.append(price_line)
    lines.append(question_line)
    message = "\n".join(lines)

    draft_message = {
        "body": message,
        "step": 3,
        "topic": "room_delta_summary",
        "requires_approval": True,
    }
    state.add_draft_message(draft_message)

    update_event_metadata(
        event_entry,
        current_step=3,
        thread_state="Awaiting Client Response",
    )
    state.set_thread_state("Awaiting Client Response")
    state.extras["persist"] = True

    gatekeeper = refresh_gatekeeper(event_entry)
    payload = {
        "client_id": state.client_id,
        "event_id": state.event_id,
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
        "delta_availability_used": True,
        "answered_question_first": True,
        "gatekeeper_passed": dict(gatekeeper),
        "reference_date": baseline_display,
        "query_date": new_display,
        "comparison": {
            "reference_status": baseline_map,
            "query_status": new_map,
        },
        "rooms_evaluated": rooms,
    }
    state.telemetry.answered_question_first = True
    state.telemetry.delta_availability_used = True
    state.telemetry.gatekeeper_passed = dict(gatekeeper)
    return GroupResult(action="room_delta_summary", payload=payload, halt=True)


def evaluate_room_statuses(db: Dict[str, Any], target_date: str | None) -> List[Dict[str, str]]:
    """[Trigger] Evaluate each configured room for the requested event date."""

    rooms = load_rooms()
    statuses: List[Dict[str, str]] = []
    for room_name in rooms:
        status = room_status_on_date(db, target_date, room_name)
        statuses.append({room_name: status})
    return statuses


def _detour_to_date(state: WorkflowState, event_entry: dict) -> GroupResult:
    """[Trigger] Redirect to Step 2 when no chosen date exists."""

    if event_entry.get("caller_step") is None:
        update_event_metadata(event_entry, caller_step=3)
    update_event_metadata(
        event_entry,
        current_step=2,
        date_confirmed=False,
        thread_state="Awaiting Client Response",
    )
    append_audit_entry(event_entry, 3, 2, "room_requires_confirmed_date")
    state.current_step = 2
    state.caller_step = 3
    state.set_thread_state("Awaiting Client Response")
    state.extras["persist"] = True
    payload = {
        "client_id": state.client_id,
        "event_id": state.event_id,
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "reason": "date_missing",
        "context": state.context_snapshot,
        "persisted": True,
    }
    gatekeeper = refresh_gatekeeper(event_entry)
    payload["gatekeeper_passed"] = dict(gatekeeper)
    state.telemetry.gatekeeper_passed = dict(gatekeeper)
    return GroupResult(action="room_detour_date", payload=payload, halt=False)


def _normalize_time_label(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace(".", ":")
    if ":" not in text:
        if text.isdigit():
            text = f"{int(text) % 24:02d}:00"
        else:
            return None
    try:
        hour, minute = text.split(":", 1)
        hour_i = int(hour)
        minute_i = int(minute)
        if not (0 <= hour_i <= 23 and 0 <= minute_i <= 59):
            return None
        return f"{hour_i:02d}:{minute_i:02d}"
    except (ValueError, TypeError):
        return None


def _format_time_range(
    query_start: Optional[str],
    query_end: Optional[str],
    baseline_start: Optional[str],
    baseline_end: Optional[str],
) -> Optional[str]:
    start = query_start or baseline_start
    end = query_end or baseline_end
    if start and end:
        return f"{start}–{end}"
    if start:
        return f"{start} start"
    if end:
        return f"until {end}"
    return None


def _room_rank(room: str) -> Tuple[int, str]:
    return ROOM_SIZE_ORDER.get(room, 999), room


def _skip_room_evaluation(state: WorkflowState, event_entry: dict) -> GroupResult:
    """[Trigger] Skip Step 3 and return to the caller when caching allows."""

    caller = event_entry.get("caller_step")
    if caller is not None:
        append_audit_entry(event_entry, 3, caller, "room_eval_cache_hit")
        update_event_metadata(event_entry, current_step=caller, caller_step=None)
        state.current_step = caller
        state.caller_step = None
    else:
        state.current_step = event_entry.get("current_step")
    state.extras["persist"] = True
    payload = {
        "client_id": state.client_id,
        "event_id": state.event_id,
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "cached": True,
        "thread_state": event_entry.get("thread_state"),
        "context": state.context_snapshot,
        "persisted": True,
    }
    gatekeeper = refresh_gatekeeper(event_entry)
    payload["gatekeeper_passed"] = dict(gatekeeper)
    state.telemetry.gatekeeper_passed = dict(gatekeeper)
    return GroupResult(action="room_eval_skipped", payload=payload, halt=False)


def _preferred_room(event_entry: dict, user_requested_room: Optional[str]) -> Optional[str]:
    """[Trigger] Determine the preferred room priority."""

    if user_requested_room:
        return user_requested_room
    requirements = event_entry.get("requirements") or {}
    preferred_room = requirements.get("preferred_room")
    if preferred_room:
        return preferred_room
    return event_entry.get("locked_room_id")


def _canonical_room_name(requested_room: str, status_map: Dict[str, str]) -> Optional[str]:
    if not requested_room:
        return None
    normalized = requested_room.strip().lower()
    if not normalized:
        return None
    for room_name in status_map:
        if room_name and room_name.strip().lower() == normalized:
            return room_name
    for room_name in ROOM_SIZE_ORDER:
        if room_name.strip().lower() == normalized:
            return room_name
    return None


def _detect_textual_room_request(message, status_map: Dict[str, str]) -> Tuple[Optional[str], bool]:
    text_parts = [message.subject or "", message.body or ""]
    text = " \n".join(part for part in text_parts if part).lower()
    if not text:
        return None, False
    keyword_match = _LOCK_KEYWORD_PATTERN.search(text)
    keyword_found = bool(keyword_match)
    candidate: Optional[str] = None
    if keyword_found:
        for room_name in status_map:
            if not room_name:
                continue
            pattern = rf"\b{re.escape(room_name.lower())}\b"
            if re.search(pattern, text):
                candidate = room_name
                break
    return candidate, keyword_found


def _same_room(existing: Optional[str], candidate: Optional[str]) -> bool:
    if not existing or not candidate:
        return False
    return existing.strip().lower() == candidate.strip().lower()


def _flatten_statuses(statuses: List[Dict[str, str]]) -> Dict[str, str]:
    """[Trigger] Convert list of {room: status} mappings into a single dict."""

    result: Dict[str, str] = {}
    for entry in statuses:
        result.update(entry)
    return result


def _select_room(preferred_room: Optional[str], status_map: Dict[str, str]) -> Tuple[Optional[str], Optional[str]]:
    """[Trigger] Choose the best room candidate based on availability."""

    if preferred_room:
        status = status_map.get(preferred_room)
        if status and status != "Confirmed":
            return preferred_room, status

    for room, status in status_map.items():
        if status == ROOM_OUTCOME_AVAILABLE:
            return room, status

    for room, status in status_map.items():
        if status == ROOM_OUTCOME_OPTION:
            return room, status

    return None, None


def _apply_hil_decision(state: WorkflowState, event_entry: Dict[str, Any], decision: str) -> GroupResult:
    """Handle HIL approval or rejection for the latest room evaluation."""

    pending = event_entry.get("room_pending_decision")
    if not pending:
        payload = {
            "client_id": state.client_id,
            "event_id": event_entry.get("event_id"),
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "reason": "no_pending_room_decision",
            "context": state.context_snapshot,
        }
        return GroupResult(action="room_hil_missing", payload=payload, halt=True)

    if decision != "approve":
        # Reset pending decision and keep awaiting further actions.
        event_entry.pop("room_pending_decision", None)
        event_entry["room_decision"] = {
            "status": "rejected",
            "reason": "hil_rejected",
            "evaluated_at": _utc_now(),
        }
        draft = {
            "body": "Approval rejected — please provide updated guidance on the room.",
            "step": 3,
            "topic": "room_hil_reject",
            "requires_approval": True,
        }
        state.add_draft_message(draft)
        update_event_metadata(event_entry, current_step=3, thread_state="Awaiting Client Response")
        state.set_thread_state("Awaiting Client Response")
        state.extras["persist"] = True
        payload = {
            "client_id": state.client_id,
            "event_id": event_entry.get("event_id"),
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "draft_messages": state.draft_messages,
            "thread_state": state.thread_state,
            "context": state.context_snapshot,
            "persisted": True,
        }
        gatekeeper = refresh_gatekeeper(event_entry)
        payload["gatekeeper_passed"] = dict(gatekeeper)
        state.telemetry.gatekeeper_passed = dict(gatekeeper)
        return GroupResult(action="room_hil_rejected", payload=payload, halt=True)

    selected_room = pending.get("selected_room")
    requirements_hash = event_entry.get("requirements_hash") or pending.get("requirements_hash")

    event_entry["room_decision"] = {
        "status": "locked",
        "reason": "hil_approved",
        "evaluated_at": _utc_now(),
    }
    update_event_metadata(
        event_entry,
        locked_room_id=selected_room,
        room_eval_hash=requirements_hash,
        current_step=4,
        thread_state="In Progress",
    )
    append_audit_entry(event_entry, 3, 4, "room_hil_approved")
    event_entry.pop("room_pending_decision", None)

    state.current_step = 4
    state.caller_step = None
    state.set_thread_state("In Progress")
    state.extras["persist"] = True

    gatekeeper = refresh_gatekeeper(event_entry)
    state.telemetry.gatekeeper_passed = dict(gatekeeper)
    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "selected_room": selected_room,
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
        "gatekeeper_passed": dict(gatekeeper),
    }
    return GroupResult(action="room_hil_approved", payload=payload, halt=False)


def _needs_better_room_alternatives(
    user_info: Dict[str, Any],
    status_map: Dict[str, str],
    event_entry: Dict[str, Any],
) -> bool:
    if (user_info or {}).get("room_feedback") != "not_good_enough":
        return False

    requirements = event_entry.get("requirements") or {}
    baseline_room = event_entry.get("locked_room_id") or requirements.get("preferred_room")
    baseline_rank = ROOM_SIZE_ORDER.get(str(baseline_room), 0)
    if baseline_rank == 0:
        return True

    larger_available = False
    for room_name, status in status_map.items():
        if ROOM_SIZE_ORDER.get(room_name, 0) > baseline_rank and status == ROOM_OUTCOME_AVAILABLE:
            larger_available = True
            break

    if not larger_available:
        return True

    participants = (requirements.get("number_of_participants") or 0)
    participants_val: Optional[int]
    try:
        participants_val = int(participants)
    except (TypeError, ValueError):
        participants_val = None

    capacity_map = {
        1: 36,
        2: 54,
        3: 96,
        4: 140,
    }
    if participants_val is not None:
        baseline_capacity = capacity_map.get(baseline_rank)
        if baseline_capacity and participants_val > baseline_capacity:
            return True

    return False


def _append_alt_dates(message: str, alt_dates: List[str]) -> str:
    if not alt_dates:
        return message
    lines = message.splitlines()
    try:
        next_step_idx = lines.index("NEXT STEP:")
    except ValueError:
        next_step_idx = len(lines)
    insert_block: List[str] = ["", "ALTERNATE DATES:"]
    insert_block.extend(f"- {date}" for date in alt_dates)
    insert_block.append("")
    updated = lines[:next_step_idx] + insert_block + lines[next_step_idx:]
    return "\n".join(updated)


def _compose_outcome_message(
    status_map: Dict[str, str],
    status: str,
    room_name: Optional[str],
    chosen_date: str,
    requirements: Dict[str, Any],
    preferred_room: Optional[str],
) -> str:
    """[Trigger] Build the draft message for the selected outcome."""

    participants = requirements.get("number_of_participants")
    layout = requirements.get("seating_layout")

    if participants and layout:
        capacity_text = f"{participants} guests in {layout}"
    elif participants:
        capacity_text = f"{participants} guests"
    elif layout:
        capacity_text = f"a {layout} layout"
    else:
        capacity_text = "your requirements"

    lines: List[str] = ["ROOM OPTIONS:"]

    candidates = _ordered_room_candidates(status_map, room_name, preferred_room)

    if not candidates:
        lines.append(f"- No rooms currently open on {chosen_date} for {capacity_text}.")
        guidance = "Share alternative dates or adjustments and I'll re-check availability."
    else:
        for candidate_name, candidate_status in candidates:
            status_label = (
                "Available"
                if candidate_status == ROOM_OUTCOME_AVAILABLE
                else "On option"
            )
            recommendation = " — Recommended" if candidate_name == room_name else ""
            lines.append(
                f"- {candidate_name} — {status_label} on {chosen_date}; fits {capacity_text}{recommendation}."
            )
        guidance = "Confirm if you'd like me to lock one of these rooms or check another option."

    lines.extend(["", "NEXT STEP:", guidance])
    return "\n".join(lines)


def _ordered_room_candidates(
    status_map: Dict[str, str],
    selected_room: Optional[str],
    preferred_room: Optional[str],
    max_items: int = 3,
) -> List[Tuple[str, str]]:
    """[Trigger] Determine the list of room candidates to surface to the user."""

    allowed_statuses = {ROOM_OUTCOME_AVAILABLE, ROOM_OUTCOME_OPTION}
    order: List[str] = []

    def _maybe_add(room: Optional[str]) -> None:
        if not room:
            return
        status = status_map.get(room)
        if status not in allowed_statuses:
            return
        if room not in order:
            order.append(room)

    _maybe_add(selected_room)
    _maybe_add(preferred_room)

    def sort_key(room: str) -> int:
        return ROOM_SIZE_ORDER.get(room, len(ROOM_SIZE_ORDER) + 1)

    available = sorted(
        (room for room, status in status_map.items() if status == ROOM_OUTCOME_AVAILABLE),
        key=sort_key,
    )
    options = sorted(
        (room for room, status in status_map.items() if status == ROOM_OUTCOME_OPTION),
        key=sort_key,
    )

    for room in available:
        _maybe_add(room)
    for room in options:
        _maybe_add(room)

    ordered = [(room, status_map[room]) for room in order[:max_items]]
    return ordered


def _compose_locked_message(
    room_name: str,
    chosen_date: str,
    requirements: Dict[str, Any],
) -> str:
    participants = requirements.get("number_of_participants")
    layout = requirements.get("seating_layout")
    if participants and layout:
        capacity_text = f"{participants} guests in {layout}"
    elif participants:
        capacity_text = f"{participants} guests"
    elif layout:
        capacity_text = f"a {layout} layout"
    else:
        capacity_text = "your requirements"
    return (
        "ROOM OPTIONS:\n"
        f"- {room_name} — Locked for {chosen_date}; fits {capacity_text}.\n\n"
        "NEXT STEP:\nI'll prepare the offer with this configuration. Let me know if you need any adjustments."
    )


def _auto_lock_confidence(status_map: Dict[str, str], selected_room: Optional[str], outcome: str) -> float:
    if outcome != ROOM_OUTCOME_AVAILABLE or not selected_room:
        return 0.0
    return 1.0 if status_map.get(selected_room) == ROOM_OUTCOME_AVAILABLE else 0.0


def _locked_room_still_valid(event_entry: Dict[str, Any]) -> bool:
    locked = event_entry.get("locked_room_id")
    if not locked:
        return False
    req_hash = event_entry.get("requirements_hash")
    eval_hash = event_entry.get("room_eval_hash")
    if req_hash and eval_hash and req_hash != eval_hash:
        return False
    requested_window = event_entry.get("requested_window") or {}
    if not requested_window.get("date_iso"):
        return False
    chosen_display = event_entry.get("chosen_date")
    if chosen_display and not _dates_align(chosen_display, requested_window.get("date_iso")):
        return False
    decision = (event_entry.get("room_decision") or {}).get("status")
    if decision and decision.lower() in {"locked", "held"}:
        return True
    return bool(locked and not req_hash and not eval_hash)


def _dates_align(display_ddmmyyyy: Optional[str], iso_value: Optional[str]) -> bool:
    if not iso_value:
        return False
    if not display_ddmmyyyy:
        return True
    converted = to_iso_date(display_ddmmyyyy)
    if converted:
        return converted == iso_value
    return True


def _reuse_locked_room(state: WorkflowState, event_entry: Dict[str, Any]) -> GroupResult:
    update_event_metadata(event_entry, current_step=4, thread_state="In Progress")
    state.current_step = 4
    state.caller_step = None
    state.set_thread_state("In Progress")
    state.extras["persist"] = True
    gatekeeper = refresh_gatekeeper(event_entry)
    payload = {
        "client_id": state.client_id,
        "event_id": state.event_id,
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
        "gatekeeper_passed": dict(gatekeeper),
        "room_status": (event_entry.get("room_decision") or {}).get("status", "locked"),
    }
    state.telemetry.room_checked = True
    state.telemetry.gatekeeper_passed = dict(gatekeeper)
    state.telemetry.detour_completed = True
    return GroupResult(action="room_lock_retained", payload=payload, halt=False)


def _finalize_room_lock(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    room_name: str,
    chosen_date: str,
    requirements: Dict[str, Any],
    room_statuses: List[Dict[str, str]],
    summary: str,
    requirements_hash: Optional[str],
    *,
    reason: str,
    audit_reason: str,
    action: str,
    final_action: str,
    auto_payload: bool,
    policy_flag: bool,
) -> GroupResult:
    autolock_meta = state.telemetry.setdefault("autolock", {})
    if auto_payload:
        autolock_meta["locked_room"] = room_name
        autolock_meta["skipped"] = False
        autolock_meta["explicit"] = False
    else:
        autolock_meta["locked_room"] = room_name
        autolock_meta["explicit"] = True
        autolock_meta.pop("skipped", None)

    if not policy_flag and reason != "user_explicit":
        raise AssertionError("room lock policy violation: auto lock attempted while disabled")

    intent_field = state.intent.value if isinstance(state.intent, IntentLabel) else state.intent
    _record_lock_attempt(
        state,
        allowed=True,
        policy=policy_flag,
        intent=str(intent_field or "event_request"),
        selected_room=room_name,
        path="room_availability._finalize_room_lock",
        reason=reason,
    )

    message = _compose_locked_message(room_name, chosen_date, requirements)
    draft_message = {
        "body": message,
        "step": 3,
        "topic": "room_locked_auto" if auto_payload else "room_locked_explicit",
        "room": room_name,
        "status": "Locked",
        "requires_approval": True,
    }
    state.add_draft_message(draft_message)

    event_entry.pop("room_pending_decision", None)
    event_entry["room_decision"] = {
        "status": "locked",
        "reason": reason,
        "evaluated_at": _utc_now(),
    }
    event_entry["room_eval_cache"] = None
    if requirements_hash:
        event_entry["room_eval_hash"] = requirements_hash
    update_event_metadata(
        event_entry,
        locked_room_id=room_name,
        current_step=4,
        thread_state="In Progress",
    )
    append_audit_entry(event_entry, 3, 4, audit_reason)

    state.current_step = 4
    state.caller_step = None
    state.set_thread_state("In Progress")
    state.extras["persist"] = True

    gatekeeper = refresh_gatekeeper(event_entry)
    payload = {
        "client_id": state.client_id,
        "event_id": state.event_id,
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "rooms": room_statuses,
        "summary": summary,
        "selected_room": room_name,
        "selected_status": "Locked",
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
        "gatekeeper_passed": dict(gatekeeper),
    }
    if auto_payload:
        payload["auto_locked"] = True

    state.telemetry.room_checked = True
    state.telemetry.gatekeeper_passed = dict(gatekeeper)
    state.telemetry.final_action = final_action
    state.telemetry.detour_completed = True
    return GroupResult(action=action, payload=payload, halt=False)


def _record_lock_attempt(
    state: WorkflowState,
    *,
    allowed: bool,
    policy: bool,
    intent: str,
    selected_room: Optional[str],
    path: str,
    reason: str,
) -> None:
    policy_flag = bool(policy)
    entry = {
        "log": "room_lock_attempt",
        "allowed": allowed,
        "policy_flag": policy_flag,
        "intent": intent,
        "selected_room": selected_room,
        "source_turn_id": state.message.msg_id,
        "path": path,
        "reason": reason,
    }
    logs = state.telemetry.setdefault("log_events", [])
    if isinstance(logs, list):
        logs.append(entry)
    else:  # defensive
        state.telemetry.log_events = [entry]
