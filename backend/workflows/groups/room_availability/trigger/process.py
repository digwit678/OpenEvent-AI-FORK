from __future__ import annotations

import copy
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import re

from backend.workflows.common.datetime_parse import to_iso_date
from backend.workflows.common.room_rules import find_better_room_dates
from backend.workflows.common.timeutils import format_iso_date_to_ddmmyyyy
from backend.workflows.common.capacity import alternative_rooms, fits_capacity
from backend.workflows.common.capture import capture_user_fields
from backend.domain import IntentLabel
from backend.workflows.common.gatekeeper import refresh_gatekeeper
from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflows.io.database import append_audit_entry, load_rooms, update_event_metadata
from backend.utils.profiler import profile_step
from backend.workflow.state import WorkflowStep, default_subflow, write_stage
from backend.services.room_eval import evaluate_rooms, rank_rooms
from backend.services.products import merge_product_requests, normalise_product_payload
from backend.workflows.common.catalog import list_free_dates

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

_LOCK_KEYWORD_PATTERN = re.compile(
    r"\b(lock|reserve|hold|secure|keep|confirm|take|proceed|choose|select|pick|go\s+with)\b",
    re.IGNORECASE,
)
_ROOM_ALIAS_MAP = {
    "room a": "Room A",
    "room b": "Room B",
    "room c": "Room C",
}


def _auto_lock_min_confidence() -> float:
    raw = os.getenv("AUTO_LOCK_MIN_CONFIDENCE", "0.85")
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return 0.85


def _extract_first_name(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    token = str(raw).strip()
    if not token:
        return None
    first = token.split()[0].strip(",. ")
    return first or None


def _compose_room_greeting(state: WorkflowState) -> str:
    profile = (state.client or {}).get("profile", {}) if state.client else {}
    raw_name = profile.get("name")
    if not raw_name and state.message:
        raw_name = getattr(state.message, "from_name", None)
    first = _extract_first_name(raw_name)
    if not first:
        return "Hello,"
    return f"Hello {first},"


def _utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


@profile_step("workflow.step3.room_availability")
def process(state: WorkflowState) -> GroupResult:
    """[Trigger] Execute Group C — room availability assessment with entry guards and caching."""

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
    state.subflow_group = "room_availability"
    write_stage(event_entry, current_step=WorkflowStep.STEP_3, subflow_group="room_availability")
    capture_user_fields(state, current_step=3, source=state.message.msg_id)

    hil_step = state.user_info.get("hil_approve_step")
    if hil_step == 3:
        decision = state.user_info.get("hil_decision") or "approve"
        return _apply_hil_decision(state, event_entry, decision)

    chosen_date = event_entry.get("chosen_date")
    if not chosen_date:
        return _detour_to_date(state, event_entry)

    if not event_entry.get("date_confirmed"):
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

    # Early explicit lock handling: parse user command before any cache short-circuit
    message_text = _message_text(state.message)
    early_explicit = _extract_explicit_lock_request(message_text)
    if early_explicit:
        # Evaluate availability and lock immediately if possible, regardless of auto-lock flag
        room_statuses = evaluate_room_statuses(state.db, chosen_date)
        status_map = _flatten_statuses(room_statuses)
        requirements = event_entry.get("requirements") or {}
        summary = summarize_room_statuses(room_statuses)
        explicit_room = _canonical_room_name(early_explicit, status_map) or (
            early_explicit if early_explicit in status_map else None
        )
        if explicit_room:
            existing_lock = event_entry.get("locked_room_id")
            explicit_status = status_map.get(explicit_room)
            same_room = _same_room(existing_lock, explicit_room)
            if same_room or explicit_status in (ROOM_OUTCOME_AVAILABLE, ROOM_OUTCOME_OPTION):
                return _finalize_room_lock(
                    state,
                    event_entry,
                    explicit_room,
                    chosen_date,
                    requirements,
                    room_statuses,
                    summary,
                    current_req_hash,
                    reason="explicit_lock",
                    audit_reason="room_lock_retained" if same_room else "room_explicit_lock",
                    action="room_lock_retained" if same_room else "room_auto_locked",
                    final_action="room_lock_retained" if same_room else "room_auto_locked",
                    auto_payload=False,
                    policy_flag=True,
                )
        # If we couldn't resolve the explicit room or it's not available, fall through to normal flow

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
    requested_products = event_entry.get("requested_products") or []
    participant_count = None
    if isinstance(state.user_info.get("participants"), int):
        participant_count = state.user_info.get("participants")
    else:
        req_participants = (event_entry.get("requirements") or {}).get("number_of_participants")
        try:
            participant_count = int(req_participants) if req_participants is not None else None
        except (TypeError, ValueError):
            participant_count = None
    user_products = state.user_info.get("products_add")
    if user_products:
        normalised_products = normalise_product_payload(user_products, participant_count=participant_count)
        if normalised_products:
            merged = merge_product_requests(requested_products, normalised_products)
            if merged != requested_products:
                event_entry["requested_products"] = merged
                requested_products = merged
                state.extras["persist"] = True
                state.user_info["products_add"] = normalised_products
    room_evaluations = evaluate_rooms(event_entry, requested_products)
    evaluation_lookup = {evaluation.record.name.lower(): evaluation for evaluation in room_evaluations}
    ranked_evaluations = rank_rooms(room_evaluations)

    preferred_room = _preferred_room(event_entry, user_requested_room)
    selected_room, selected_status = _select_room(preferred_room, status_map)
    requirements = event_entry.get("requirements") or {}
    canonical_user_room = _canonical_room_name(user_requested_room, status_map) if user_requested_room else None
    attendee_count = _coerce_attendees(requirements.get("number_of_participants"))
    layout_pref = requirements.get("seating_layout")
    if canonical_user_room and selected_room and canonical_user_room == selected_room:
        evaluation = evaluation_lookup.get(selected_room.lower())
        if not fits_capacity(selected_room, attendee_count, layout_pref) and not (
            evaluation and evaluation.status in {"Available", "Option"}
        ):
            return _capacity_shortfall(state, event_entry, selected_room, chosen_date, attendee_count, layout_pref)

    outcome = selected_status or ROOM_OUTCOME_UNAVAILABLE
    auto_lock_score = _auto_lock_confidence(status_map, selected_room, outcome)
    intent_label = state.intent or IntentLabel.EVENT_REQUEST
    if isinstance(intent_label, str):
        try:
            intent_label = IntentLabel(intent_label)
        except ValueError:
            intent_label = IntentLabel.NON_EVENT
    intent_value = intent_label.value if isinstance(intent_label, IntentLabel) else str(intent_label).lower()
    allow_auto = str(os.getenv("AUTO_LOCK_SINGLE_ROOM", "false")).strip().lower() in {"1", "true", "yes", "on"}
    message_text = _message_text(state.message)
    text_explicit_room = _extract_explicit_lock_request(message_text)
    requested_room_id = user_requested_room or ""
    canonical_user_room = _canonical_room_name(requested_room_id, status_map)
    explicit_from_intent = isinstance(intent_label, IntentLabel) and intent_label == IntentLabel.EDIT_ROOM

    explicit_room: Optional[str] = None
    explicit_reason: Optional[str] = None
    explicit_policy_allowed = True
    if text_explicit_room:
        explicit_room = _canonical_room_name(text_explicit_room, status_map) or (
            text_explicit_room if text_explicit_room in status_map else None
        )
        explicit_reason = "explicit_lock"
        explicit_policy_allowed = True
    elif explicit_from_intent and canonical_user_room:
        explicit_room = canonical_user_room
        explicit_reason = "user_explicit"

    existing_lock = event_entry.get("locked_room_id")
    if text_explicit_room and not explicit_room:
        _record_lock_attempt(
            state,
            allowed=False,
            policy=True,
            intent=intent_value,
            selected_room=None,
            path="room_availability.process",
            reason="room_not_recognized",
        )

    explicit_status = status_map.get(explicit_room) if explicit_room else None
    if explicit_room and explicit_reason:
        same_room = _same_room(existing_lock, explicit_room)
        if same_room or explicit_status in (ROOM_OUTCOME_AVAILABLE, ROOM_OUTCOME_OPTION):
            audit_reason = (
                explicit_reason
                if explicit_reason == "explicit_lock"
                else ("room_lock_retained" if same_room else "room_user_locked")
            )
            action = "room_lock_retained" if same_room else "room_auto_locked"
            return _finalize_room_lock(
                state,
                event_entry,
                explicit_room,
                chosen_date,
                requirements,
                room_statuses,
                summary,
                current_req_hash,
                reason=explicit_reason,
                audit_reason=audit_reason,
                action=action,
                final_action=action,
                auto_payload=False,
                policy_flag=explicit_policy_allowed,
            )
        _record_lock_attempt(
            state,
            allowed=False,
            policy=explicit_policy_allowed,
            intent=intent_value,
            selected_room=explicit_room,
            path="room_availability.process",
            reason=f"room_status_{explicit_status or 'unknown'}",
        )
        autolock_meta = state.telemetry.setdefault("autolock", {})
        autolock_meta["considered"] = True
        autolock_meta["allowed"] = explicit_policy_allowed
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
    if auto_lock_candidate and allow_auto:
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
            policy_flag=allow_auto,
        )

    if auto_lock_candidate:
        autolock_meta = state.telemetry.setdefault("autolock", {})
        autolock_meta["considered"] = True
        autolock_meta["allowed"] = allow_auto
        autolock_meta["explicit"] = False
        autolock_meta["skipped"] = True
        if "room_selection" not in state.telemetry.deferred_intents:
            state.telemetry.deferred_intents.append("room_selection")
        _record_lock_attempt(
            state,
            allowed=False,
            policy=allow_auto,
            intent=intent_value,
            selected_room=selected_room,
            path="room_availability.process",
            reason="blocked_by_policy_no_explicit_selection",
        )

    draft_text, room_eval_payloads, manager_request_needed = _compose_outcome_message(
        state,
        ranked_evaluations,
        chosen_date,
        event_entry.get("requested_window") or {},
        selected_room,
        requirements,
        outcome,
        state.db,
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
        "room_evaluations": room_eval_payloads,
    }
    if manager_request_needed:
        draft_message["manager_special_request"] = True
    if alt_dates:
        draft_message["alt_dates_for_better_room"] = alt_dates
    state.add_draft_message(draft_message)

    event_entry["room_pending_decision"] = {
        "selected_room": selected_room,
        "selected_status": outcome,
        "requirements_hash": current_req_hash,
        "summary": summary,
        "evaluations": room_eval_payloads,
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
        "room_evaluations": room_eval_payloads,
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
    }
    if manager_request_needed:
        payload["manager_special_request"] = True
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
    write_stage(
        event_entry,
        current_step=WorkflowStep.STEP_2,
        subflow_group="date_confirmation",
        caller_step=WorkflowStep.STEP_3,
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


def _message_text(message) -> str:
    if not message:
        return ""
    parts: List[str] = []
    subject = getattr(message, "subject", None)
    body = getattr(message, "body", None)
    if subject:
        parts.append(str(subject))
    if body:
        parts.append(str(body))
    return " \n".join(part for part in parts if part)


def _extract_explicit_lock_request(text: str) -> Optional[str]:
    if not text:
        return None
    lowered = text.lower()
    if not _LOCK_KEYWORD_PATTERN.search(lowered):
        return None
    # Match "room a", "room-b", "the room b", etc.
    match = re.search(r"\b(?:the\s+)?room[-\s]*([ab])\b", lowered)
    if match:
        letter = match.group(1).upper()
        return f"Room {letter}"
    # Fallback to alias map lookups (only canonical room labels).
    for alias, canonical in _ROOM_ALIAS_MAP.items():
        if canonical not in {"Room A", "Room B"}:
            continue
        alias_pattern = re.sub(r"\s+", r"\\s*", re.escape(alias))
        if re.search(rf"\b{alias_pattern}\b", lowered):
            return canonical
    return None


def _canonical_room_name(requested_room: str, status_map: Dict[str, str]) -> Optional[str]:
    if not requested_room:
        return None
    normalized = re.sub(r"\s+", " ", requested_room).strip().lower()
    if not normalized:
        return None
    for room_name in status_map:
        if room_name and room_name.strip().lower() == normalized:
            return room_name
    for room_name in ROOM_SIZE_ORDER:
        if room_name.strip().lower() == normalized:
            return room_name
    alias_match = _ROOM_ALIAS_MAP.get(normalized)
    if alias_match:
        return alias_match
    return None


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
    insert_block: List[str] = ["", "Alternative dates:"]
    insert_block.extend(f"- {date}" for date in alt_dates)
    insert_block.append("")
    updated = lines[:next_step_idx] + insert_block + lines[next_step_idx:]
    return "\n".join(updated)


def _compose_outcome_message(
    state: WorkflowState,
    evaluations: List["RoomEvaluation"],
    chosen_date: str,
    requested_window: Dict[str, Any],
    selected_room: Optional[str],
    requirements: Dict[str, Any],
    overall_status: str,
    db: Dict[str, Any],
) -> Tuple[str, List[Dict[str, Any]], bool]:
    """Build the room availability reply using enriched evaluation data."""

    time_range = ""
    start_time = requested_window.get("start_time")
    end_time = requested_window.get("end_time")
    if start_time and end_time:
        time_range = f"{start_time}–{end_time}"

    top_evaluations = evaluations[:3]
    available_exists = any(evaluation.status == "Available" for evaluation in evaluations)
    manager_special_needed = not available_exists or any(e.missing_products for e in evaluations)

    descriptor = chosen_date + (f" {time_range}" if time_range else "")
    greeting = _compose_room_greeting(state)
    context_line = f"Thanks for the details — here's how {descriptor.strip()} is looking on our side."

    lines: List[str] = [greeting, context_line, "", "ROOM OPTIONS:"]
    if top_evaluations and available_exists:
        for evaluation in top_evaluations:
            date_options = _room_date_options(evaluation, requested_window, db, chosen_date)
            lines.append(
                _format_evaluation_line(
                    evaluation,
                    chosen_date,
                    time_range,
                    selected_room,
                    date_options,
                )
            )
    elif top_evaluations:
        descriptor = f"{chosen_date}" + (f" {time_range}" if time_range else "")
        lines.append(f"- None of our rooms are free on {descriptor} for your current setup.")
        lines.append("")
        lines.append("INFO:")
        for evaluation in top_evaluations:
            reason_text = "; ".join(evaluation.reasons) if evaluation.reasons else "No availability at that time."
            lines.append(f"- {evaluation.record.name}: {reason_text}")
    else:
        lines.append("- No room data available right now.")

    if manager_special_needed:
        lines.extend(
            [
                "",
                "NEXT STEP:",
                "- Share another date or time so I can check again.",
                "- Adjust the guest count or layout.",
                "- Ask me to create a manager special request to explore alternatives.",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "NEXT STEP:",
                "- Tell me which room you'd like me to reserve.",
                "- Need a different configuration? Let me know and I’ll check additional options.",
            ]
        )

    room_payloads = [evaluation.to_payload() for evaluation in top_evaluations]
    return "\n".join(lines), room_payloads, manager_special_needed


def _room_date_options(
    evaluation: "RoomEvaluation",
    requested_window: Dict[str, Any],
    db: Dict[str, Any],
    chosen_date: str,
) -> List[str]:
    iso_value = requested_window.get("date_iso")
    anchor_date = None
    if iso_value:
        try:
            anchor_date = datetime.fromisoformat(iso_value).date()
        except ValueError:
            anchor_date = None
    if anchor_date is None and chosen_date:
        try:
            anchor_date = datetime.strptime(chosen_date, "%d.%m.%Y").date()
        except ValueError:
            anchor_date = None
    if anchor_date is None:
        return []

    raw_dates = list_free_dates(
        anchor_month=anchor_date.month,
        anchor_day=anchor_date.day,
        count=3,
        db=db,
        preferred_room=evaluation.record.name,
    )
    formatted: List[str] = []
    for iso in raw_dates:
        display = format_iso_date_to_ddmmyyyy(iso) or iso
        if display not in formatted:
            formatted.append(display)
    return formatted


def _format_evaluation_line(
    evaluation: "RoomEvaluation",
    chosen_date: str,
    time_range: str,
    selected_room: Optional[str],
    date_options: List[str],
) -> str:
    line = f"- {evaluation.record.name} — {evaluation.status} on {chosen_date}"
    if time_range:
        line += f" {time_range}"

    segments: List[str] = []
    if evaluation.coverage_total > 0:
        segments.append(f"Req fit: {evaluation.coverage_matched}/{evaluation.coverage_total}")
    elif evaluation.coverage_matched:
        segments.append(f"Req fit: {evaluation.coverage_matched}")
    if evaluation.matched_features:
        segments.append("Matched: " + ", ".join(f"{feature} ✓" for feature in evaluation.matched_features))
    if evaluation.missing_features:
        segments.append("Missing: " + ", ".join(f"{feature} ✗" for feature in evaluation.missing_features))
    if evaluation.capacity_slack is not None:
        if evaluation.capacity_slack >= 0:
            segments.append(f"Capacity slack: +{evaluation.capacity_slack}")
        else:
            segments.append(f"Capacity shortfall: {evaluation.capacity_slack}")
    if evaluation.reasons and evaluation.status != "Available":
        segments.append("; ".join(evaluation.reasons))
    if date_options:
        segments.append("Alternative dates: " + ", ".join(date_options))
    if evaluation.available_products:
        product_labels = ", ".join(item.get("name", "Item") for item in evaluation.available_products if item.get("name"))
        if product_labels:
            segments.append(f"Products: {product_labels}")
    if evaluation.missing_products:
        missing_labels = ", ".join(item.get("name", "Item") for item in evaluation.missing_products if item.get("name"))
        if missing_labels:
            segments.append(f"Missing products: {missing_labels}")

    if segments:
        line += "; " + "; ".join(segments)
    if selected_room and evaluation.record.name.lower() == selected_room.lower():
        line += " — Recommended"
    return line


def _coerce_attendees(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _capacity_shortfall(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    room_name: str,
    chosen_date: str,
    attendees: Optional[int],
    layout: Optional[str],
) -> GroupResult:
    descriptor = f"{attendees} guests" if attendees else "your group"
    if layout:
        descriptor = f"{descriptor} in {layout}"
    lines = [
        "ROOM OPTIONS:",
        f"- {room_name} cannot comfortably host {descriptor} on {chosen_date}.",
    ]
    alternatives = alternative_rooms(event_entry.get("requested_window", {}).get("date_iso"), attendees, layout)
    for alt in alternatives[:3]:
        cap_text = ""
        if layout and alt.get("layout_max"):
            cap_text = f"{layout} up to {alt['layout_max']}"
        elif alt.get("max"):
            cap_text = f"up to {alt['max']} guests"
        else:
            cap_text = "flexible capacity"
        lines.append(f"- {alt['name']} — {cap_text}.")
    lines.extend(
        [
            "",
            "NEXT STEP:",
            "- Proceed with Room Selection? Reply with an alternative room and I'll recheck availability.",
        ]
    )
    message = "\n".join(lines)
    draft = {
        "body": message,
        "step": 3,
        "topic": "room_capacity_shortfall",
        "requires_approval": True,
    }
    state.add_draft_message(draft)
    update_event_metadata(event_entry, current_step=3, thread_state="Awaiting Client Response")
    state.current_step = 3
    state.set_thread_state("Awaiting Client Response")
    state.extras["persist"] = True
    gatekeeper = refresh_gatekeeper(event_entry)
    state.telemetry.gatekeeper_passed = dict(gatekeeper)
    payload = {
        "client_id": state.client_id,
        "event_id": state.event_id,
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "draft_messages": state.draft_messages,
        "alternatives": alternatives,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
        "gatekeeper_passed": dict(gatekeeper),
    }
    state.telemetry.answered_question_first = True
    return GroupResult(action="room_capacity_blocked", payload=payload, halt=True)


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

    if not policy_flag and reason not in {"user_explicit", "explicit_lock"}:
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
    halt_value = not auto_payload
    return GroupResult(action=action, payload=payload, halt=halt_value)


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
