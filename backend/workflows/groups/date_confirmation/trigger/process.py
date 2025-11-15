from __future__ import annotations

import hashlib
from dataclasses import dataclass
from collections import Counter
from datetime import datetime, time, date, timedelta
from calendar import monthrange
from typing import Any, Dict, List, Optional, Sequence, Tuple
import datetime as dt
import re

from backend.debug.hooks import (
    set_subloop,
    trace_db_read,
    trace_db_write,
    trace_entity,
    trace_marker,
    trace_state,
    trace_step,
    trace_gate,
    trace_general_qa_status,
)
from backend.workflows.common.datetime_parse import (
    build_window_iso,
    parse_first_date,
    parse_time_range,
    to_ddmmyyyy,
    to_iso_date,
)
from backend.workflows.common.prompts import append_footer, format_sections_with_headers
from backend.workflows.common.catalog import list_free_dates
from backend.workflows.common.capture import capture_user_fields, promote_fields
from backend.workflows.common.sorting import rank_rooms
from backend.workflows.common.requirements import requirements_hash
from backend.workflows.common.gatekeeper import refresh_gatekeeper
from backend.workflows.common.timeutils import format_iso_date_to_ddmmyyyy, parse_ddmmyyyy
from backend.workflows.common.menu_options import build_menu_payload, format_menu_line
from backend.workflows.common.general_qna import render_general_qna_reply, enrich_general_qna_step2, _fallback_structured_body
from backend.workflows.change_propagation import detect_change_type, route_change_on_updated_variable
from backend.workflows.qna.engine import build_structured_qna_result
from backend.workflows.qna.extraction import ensure_qna_extraction
from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflows.groups.intake.condition.checks import suggest_dates
from backend.workflows.groups.room_availability.condition.decide import room_status_on_date
from backend.workflows.io.dates import next5
from backend.workflows.io.database import (
    append_audit_entry,
    link_event_to_client,
    load_rooms,
    tag_message,
    update_event_metadata,
)
from backend.workflows.nlu import detect_general_room_query
from backend.utils.profiler import profile_step
from backend.services.availability import next_five_venue_dates, validate_window
from backend.utils.dates import MONTH_INDEX_TO_NAME, from_hints
from backend.workflow.state import WorkflowStep, default_subflow, write_stage

from ..condition.decide import is_valid_ddmmyyyy

__workflow_role__ = "trigger"


@dataclass
class ConfirmationWindow:
    """Resolved confirmation payload for the requested event window."""

    display_date: str
    iso_date: str
    start_time: Optional[str]
    end_time: Optional[str]
    start_iso: Optional[str]
    end_iso: Optional[str]
    inherited_times: bool
    partial: bool
    source_message_id: Optional[str]


WindowHints = Tuple[Optional[str], Optional[Any], Optional[str]]

_MONTH_NAME_TO_INDEX = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

_WEEKDAY_NAME_TO_INDEX = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}

def _thread_id(state: WorkflowState) -> str:
    if state.thread_id:
        return str(state.thread_id)
    if state.client_id:
        return str(state.client_id)
    message = state.message
    if message and message.msg_id:
        return str(message.msg_id)
    return "unknown-thread"


AFFIRMATIVE_TOKENS = {
    "yes",
    "yep",
    "sure",
    "sounds good",
    "that works",
    "works for me",
    "confirm",
    "confirmed",
    "let's do it",
    "go ahead",
    "we agree",
    "all good",
    "perfect",
}

CONFIRMATION_KEYWORDS = {
    "we'll go with",
    "we will go with",
    "we'll take",
    "we will take",
    "we confirm",
    "please confirm",
    "lock in",
    "book it",
    "reserve it",
    "confirm the date",
    "confirming",
    "take the",
    "take ",
}


def _extract_first_name(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    candidate = str(raw).strip()
    if not candidate:
        return None
    token = candidate.split()[0].strip(",. ")
    return token or None


_SIGNATURE_MARKERS = (
    "best regards",
    "kind regards",
    "regards",
    "many thanks",
    "thanks",
    "thank you",
    "cheers",
    "beste grüsse",
    "freundliche grüsse",
)


def _extract_signature_name(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for idx, line in enumerate(lines):
        lowered = line.lower()
        if any(marker in lowered for marker in _SIGNATURE_MARKERS):
            if idx + 1 < len(lines):
                candidate = lines[idx + 1].strip(", ")
                if candidate and len(candidate.split()) <= 4:
                    return candidate
    if lines:
        tail = lines[-1]
        if 1 <= len(tail.split()) <= 4:
            return tail
    return None


def _has_range_tokens(user_info: Dict[str, Any], event_entry: Dict[str, Any]) -> bool:
    return any(
        (
            user_info.get("range_query_detected"),
            event_entry.get("range_query_detected"),
            user_info.get("vague_month"),
            event_entry.get("vague_month"),
            user_info.get("vague_weekday"),
            event_entry.get("vague_weekday"),
            user_info.get("vague_time_of_day"),
            event_entry.get("vague_time_of_day"),
        )
    )


def _range_query_pending(user_info: Dict[str, Any], event_entry: Dict[str, Any]) -> bool:
    if not _has_range_tokens(user_info, event_entry):
        return False
    if event_entry.get("date_confirmed"):
        return False
    if user_info.get("event_date") or user_info.get("date"):
        return False
    pending_window = event_entry.get("pending_date_confirmation") or {}
    if pending_window.get("iso_date"):
        return False
    return True


def _emit_step2_snapshot(
    state: WorkflowState,
    event_entry: dict,
    *,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    thread_id = _thread_id(state)
    snapshot: Dict[str, Any] = {
        "step": 2,
        "current_step": 2,
        "thread_state": event_entry.get("thread_state") or state.thread_state,
        "chosen_date": event_entry.get("chosen_date"),
        "date_confirmed": event_entry.get("date_confirmed"),
        "range_query_detected": event_entry.get("range_query_detected"),
        "vague_month": event_entry.get("vague_month") or (state.user_info or {}).get("vague_month"),
        "vague_weekday": event_entry.get("vague_weekday") or (state.user_info or {}).get("vague_weekday"),
    }
    if extra:
        snapshot.update(extra)
    trace_state(thread_id, "Step2_Date", snapshot)


def _compose_greeting(state: WorkflowState) -> str:
    profile = (state.client or {}).get("profile", {}) if state.client else {}
    user_info_name = None
    if state.user_info:
        user_info_name = state.user_info.get("name") or state.user_info.get("company_contact")
    raw_name = (
        user_info_name
        or profile.get("name")
        or _extract_signature_name(state.message.body)
        or state.message.from_name
    )
    first = _extract_first_name(raw_name)
    if not first:
        return "Hello,"
    return f"Hello {first},"


def _with_greeting(state: WorkflowState, body: str) -> str:
    greeting = _compose_greeting(state)
    if not body:
        return greeting
    if body.startswith(greeting):
        return body
    return f"{greeting}\n\n{body}"


def _future_fridays_in_may_june(anchor: date, count: int = 4) -> List[str]:
    results: List[str] = []
    year = anchor.year
    while len(results) < count:
        window_start = date(year, 5, 1)
        window_end = date(year, 6, 30)
        cursor = max(anchor, window_start)
        while cursor <= window_end and len(results) < count:
            if cursor.weekday() == 4 and cursor >= anchor:
                results.append(cursor.isoformat())
            cursor += timedelta(days=1)
        year += 1
    return results[:count]


def _maybe_fuzzy_friday_candidates(text: str, anchor: date) -> List[str]:
    lowered = text.lower()
    if "friday" not in lowered:
        return []
    if "late spring" in lowered or ("spring" in lowered and "late" in lowered):
        return _future_fridays_in_may_june(anchor)
    return []


def _next_matching_date(original: date, reference: date) -> date:
    candidate_year = max(reference.year, original.year)
    while True:
        try:
            candidate = original.replace(year=candidate_year)
        except ValueError:
            clamped_day = min(original.day, 28)
            candidate = date(candidate_year, original.month, clamped_day)
        if candidate > reference:
            return candidate
        candidate_year += 1


@trace_step("Step2_Date")
@profile_step("workflow.step2.date_confirmation")
def process(state: WorkflowState) -> GroupResult:
    """[Trigger] Run Group B — date negotiation and confirmation."""

    event_entry = state.event_entry
    if not event_entry:
        payload = {
            "client_id": state.client_id,
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "reason": "missing_event_record",
            "context": state.context_snapshot,
        }
        return GroupResult(action="date_invalid", payload=payload, halt=True)

    state.current_step = 2
    state.subflow_group = "date_confirmation"
    write_stage(event_entry, current_step=WorkflowStep.STEP_2, subflow_group="date_confirmation")

    capture_user_fields(state, current_step=2, source=state.message.msg_id if state.message else None)

    message_text = _message_text(state)
    classification = detect_general_room_query(message_text, state)
    state.extras["_general_qna_classification"] = classification
    state.extras["general_qna_detected"] = bool(classification.get("is_general"))
    classification.setdefault("primary", "general_qna")
    if not classification.get("secondary"):
        classification["secondary"] = ["general"]
    thread_id = _thread_id(state)
    if thread_id:
        trace_marker(
            thread_id,
            "QNA_CLASSIFY",
            detail="general_room_query" if classification["is_general"] else "not_general",
            data={
                "heuristics": classification.get("heuristics"),
                "parsed": classification.get("parsed"),
                "constraints": classification.get("constraints"),
                "llm_called": classification.get("llm_called"),
                "llm_result": classification.get("llm_result"),
                "cached": classification.get("cached"),
            },
            owner_step="Step2_Date",
        )
    qa_payload = _maybe_general_qa_payload(state)

    # [CHANGE DETECTION] Tap incoming stream BEFORE Q&A dispatch to detect client revisions
    # ("actually we're 50 now") and route them back to dependent nodes while hashes stay valid.
    user_info = state.user_info or {}
    change_type = detect_change_type(event_entry, user_info, message_text=message_text)

    if change_type is not None:
        # Change detected: route it per DAG rules and skip Q&A dispatch
        decision = route_change_on_updated_variable(event_entry, change_type, from_step=2)

        # Trace logging for parity with Step 1
        if thread_id:
            trace_marker(
                thread_id,
                "CHANGE_DETECTED",
                detail=f"change_type={change_type.value}",
                data={
                    "change_type": change_type.value,
                    "from_step": 2,
                    "to_step": decision.next_step,
                    "caller_step": decision.updated_caller_step,
                    "needs_reeval": decision.needs_reeval,
                    "skip_reason": decision.skip_reason,
                },
                owner_step="Step2_Date",
            )

        # Apply routing decision: update current_step and caller_step
        if decision.updated_caller_step is not None:
            update_event_metadata(event_entry, caller_step=decision.updated_caller_step)

        if decision.next_step != 2:
            update_event_metadata(event_entry, current_step=decision.next_step)

            # Clear room lock for date/requirements changes
            if change_type.value in ("date", "requirements") and decision.next_step in (2, 3):
                if decision.next_step == 2:
                    update_event_metadata(
                        event_entry,
                        date_confirmed=False,
                        room_eval_hash=None,
                        locked_room_id=None,
                    )

            append_audit_entry(event_entry, 2, decision.next_step, f"{change_type.value}_change_detected")

            # Skip Q&A: return detour signal
            state.current_step = decision.next_step
            state.set_thread_state("In Progress")
            state.extras["persist"] = True
            state.extras["change_detour"] = True

            payload = {
                "client_id": state.client_id,
                "event_id": event_entry.get("event_id"),
                "intent": state.intent.value if state.intent else None,
                "confidence": round(state.confidence or 0.0, 3),
                "change_type": change_type.value,
                "detour_to_step": decision.next_step,
                "caller_step": decision.updated_caller_step,
                "thread_state": state.thread_state,
                "context": state.context_snapshot,
                "persisted": True,
            }
            return GroupResult(action="change_detour", payload=payload, halt=False)

    # No change detected: proceed with Q&A dispatch as normal
    general_qna_applicable = classification.get("is_general") and not bool(event_entry.get("date_confirmed"))
    if general_qna_applicable:
        result = _present_general_room_qna(state, event_entry, classification, thread_id, qa_payload)
        enrich_general_qna_step2(state, classification)
        return result

    pending_future_payload = event_entry.get("pending_future_confirmation")
    if pending_future_payload:
        body_text = state.message.body or ""
        if _message_mentions_new_date(body_text):
            event_entry.pop("pending_future_confirmation", None)
        elif _message_signals_confirmation(body_text):
            pending_future_window = _window_from_payload(pending_future_payload)
            event_entry.pop("pending_future_confirmation", None)
            if pending_future_window:
                return _finalize_confirmation(state, event_entry, pending_future_window)

    user_info = state.user_info or {}
    range_pending = _range_query_pending(user_info, event_entry)

    window = None if range_pending else _resolve_confirmation_window(state, event_entry)
    if window is None:
        return _present_candidate_dates(state, event_entry)

    if window.partial:
        filled = _maybe_complete_from_time_hint(window, state, event_entry)
        if filled:
            window = filled
        else:
            return _handle_partial_confirmation(state, event_entry, window)

    pending_window_payload = event_entry.get("pending_date_confirmation")
    if pending_window_payload:
        pending_window = _window_from_payload(pending_window_payload)
        if _is_affirmative_reply(state.message.body or "") and pending_window:
            event_entry.pop("pending_date_confirmation", None)
            return _finalize_confirmation(state, event_entry, pending_window)
        if _message_mentions_new_date(state.message.body or ""):
            event_entry.pop("pending_date_confirmation", None)
        elif pending_window and not window.partial:
            if (
                pending_window.iso_date == window.iso_date
                and pending_window.start_time == window.start_time
                and pending_window.end_time == window.end_time
            ):
                event_entry.pop("pending_date_confirmation", None)
                return _finalize_confirmation(state, event_entry, window)

    reference_day = _reference_date_from_state(state)
    feasible, reason = validate_window(window.iso_date, window.start_time, window.end_time, reference=reference_day)
    if not feasible:
        return _present_candidate_dates(state, event_entry, reason)

    auto_accept = _should_auto_accept_first_date(event_entry) and not range_pending
    if user_info.get("date") or user_info.get("event_date"):
        auto_accept = True
    if _message_signals_confirmation(state.message.body or "") or auto_accept:
        event_entry.pop("pending_date_confirmation", None)
        return _finalize_confirmation(state, event_entry, window)

    event_entry["pending_date_confirmation"] = _window_payload(window)
    return _prompt_confirmation(state, event_entry, window)


def _present_candidate_dates(
    state: WorkflowState,
    event_entry: dict,
    reason: Optional[str] = None,
) -> GroupResult:
    """[Trigger] Provide five deterministic candidate dates to the client."""

    user_text = f"{state.message.subject or ''} {state.message.body or ''}".strip()
    reference_day = _reference_date_from_state(state)
    fuzzy_candidates = _maybe_fuzzy_friday_candidates(user_text, reference_day)

    requirements = event_entry.get("requirements") or {}
    preferred_room = requirements.get("preferred_room") or "Not specified"
    anchor = parse_first_date(user_text, fallback_year=reference_day.year)
    anchor_dt = datetime.combine(anchor, time(hour=12)) if anchor else None

    formatted_dates: List[str] = []
    seen_iso: set[str] = set()
    limit = 4 if reason and "past" in reason.lower() else 5
    event_entry.pop("pending_future_confirmation", None)

    week_scope = _resolve_week_scope(state, reference_day)
    week_label_value: Optional[str] = None

    if week_scope:
        limit = min(len(week_scope["dates"]), 7)

    if week_scope:
        for iso_value in week_scope["dates"]:
            if iso_value in seen_iso or _iso_date_is_past(iso_value):
                continue
            seen_iso.add(iso_value)
            formatted_dates.append(iso_value)
        week_label_value = week_scope["label"]
        event_entry["week_index"] = week_scope["week_index"]
        event_entry["weekdays_hint"] = list(week_scope.get("weekdays_hint") or [])
        event_entry["window_scope"] = {
            "month": week_scope["month_label"],
            "week_index": week_scope["week_index"],
            "weekdays_hint": list(week_scope.get("weekdays_hint") or []),
        }
        update_event_metadata(
            event_entry,
            week_index=week_scope["week_index"],
            weekdays_hint=list(week_scope.get("weekdays_hint") or []),
            window_scope=event_entry["window_scope"],
        )
    elif fuzzy_candidates:
        for iso_value in fuzzy_candidates:
            if iso_value in seen_iso or _iso_date_is_past(iso_value):
                continue
            seen_iso.add(iso_value)
            formatted_dates.append(iso_value)
    else:
        constraints_for_window = {
            "vague_month": state.user_info.get("vague_month") or event_entry.get("vague_month"),
            "weekday": state.user_info.get("vague_weekday") or event_entry.get("vague_weekday"),
            "time_of_day": state.user_info.get("vague_time_of_day") or event_entry.get("vague_time_of_day"),
        }
        window_hints = _resolve_window_hints(constraints_for_window, state)
        strict_window = _has_window_constraints(window_hints)
        if strict_window:
            hinted_dates = _candidate_dates_for_constraints(
                state,
                constraints_for_window,
                limit=limit,
                window_hints=window_hints,
                strict=True,
            )
            for iso_value in hinted_dates:
                if not iso_value or iso_value in seen_iso or _iso_date_is_past(iso_value):
                    continue
                seen_iso.add(iso_value)
                formatted_dates.append(iso_value)

        candidate_dates_ddmmyyyy: List[str] = suggest_dates(
            state.db,
            preferred_room=preferred_room,
            start_from_iso=anchor_dt.isoformat() if anchor_dt else state.message.ts,
            days_ahead=45,
            max_results=5,
        )
        trace_db_read(
            _thread_id(state),
            "Step2_Date",
            "db.dates.next5",
            {
                "preferred_room": preferred_room,
                "anchor": anchor_dt.isoformat() if anchor_dt else state.message.ts,
                "result_count": len(candidate_dates_ddmmyyyy),
            },
        )

        for raw in candidate_dates_ddmmyyyy:
            iso_value = to_iso_date(raw)
            if not iso_value:
                continue
            if _iso_date_is_past(iso_value) or iso_value in seen_iso:
                continue
            seen_iso.add(iso_value)
            formatted_dates.append(iso_value)

        if len(formatted_dates) < limit:
            skip = {_safe_parse_iso_date(iso) for iso in seen_iso}
            supplemental = next_five_venue_dates(anchor_dt, skip_dates={dt for dt in skip if dt is not None})
            trace_db_read(
                _thread_id(state),
                "Step2_Date",
                "db.dates.next5",
                {
                    "preferred_room": preferred_room,
                    "anchor": anchor_dt.isoformat() if anchor_dt else state.message.ts,
                    "result_count": len(supplemental),
                },
            )
            for candidate in supplemental:
                iso_candidate = candidate if isinstance(candidate, str) else candidate.isoformat()
                if iso_candidate in seen_iso:
                    continue
                seen_iso.add(iso_candidate)
                formatted_dates.append(iso_candidate)
                if len(formatted_dates) >= limit:
                    break

    if fuzzy_candidates:
        formatted_dates = formatted_dates[:4]
    formatted_dates = formatted_dates[:limit]

    start_hint = _normalize_time_value(state.user_info.get("start_time"))
    end_hint = _normalize_time_value(state.user_info.get("end_time"))
    start_pref = start_hint or "18:00"
    end_pref = end_hint or "22:00"
    if start_pref and end_pref:
        slot_text = f"{start_pref}–{end_pref}"
    elif start_pref:
        slot_text = start_pref
    elif end_pref:
        slot_text = end_pref
    else:
        slot_text = "18:00–22:00"

    greeting = _compose_greeting(state)
    message_lines: List[str] = [greeting, ""]

    original_requested = parse_first_date(user_text, fallback_year=reference_day.year)
    future_suggestion = None
    future_display: Optional[str] = None
    if original_requested and original_requested < reference_day:
        future_suggestion = _next_matching_date(original_requested, reference_day)

    if reason and "past" in reason.lower() and future_suggestion:
        original_display = (
            format_iso_date_to_ddmmyyyy(original_requested.isoformat())
            or original_requested.strftime("%d.%m.%Y")
        )
        future_display = (
            format_iso_date_to_ddmmyyyy(future_suggestion.isoformat())
            or future_suggestion.strftime("%d.%m.%Y")
        )
        message_lines.append(f"It looks like {original_display} has already passed. Would {future_display} work for you instead?")

        future_iso = future_suggestion.isoformat()
        start_iso_val = end_iso_val = None
        if start_hint and end_hint:
            try:
                start_iso_val, end_iso_val = build_window_iso(
                    future_iso,
                    _to_time(start_hint),
                    _to_time(end_hint),
                )
            except ValueError:
                start_iso_val = end_iso_val = None
        pending_window = ConfirmationWindow(
            display_date=future_display,
            iso_date=future_iso,
            start_time=start_hint,
            end_time=end_hint,
            start_iso=start_iso_val,
            end_iso=end_iso_val,
            inherited_times=False,
            partial=not (start_hint and end_hint),
            source_message_id=state.message.msg_id,
        )
        event_entry["pending_future_confirmation"] = _window_payload(pending_window)
    elif reason:
        message_lines.append(reason)
    else:
        message_lines.append("Thanks for the briefing — here are the next available slots that fit your preferred window.")

    if future_suggestion:
        target_month = future_suggestion.strftime("%Y-%m")
        filtered_dates = [iso for iso in formatted_dates if iso.startswith(target_month)]
        if filtered_dates:
            formatted_dates = filtered_dates[:4]

    sample_dates = formatted_dates[:4]
    if week_scope:
        sample_dates = list(formatted_dates)
    day_line, day_year = _format_day_list(sample_dates)
    month_hint_value = (
        week_scope["month_label"]
        if week_scope
        else state.user_info.get("vague_month") or event_entry.get("vague_month")
    )
    month_for_line = week_label_value or month_hint_value or _month_label_from_dates(sample_dates, "February")
    date_header_label = _date_header_label(month_hint_value, week_label_value)
    weekday_hint_value = state.user_info.get("vague_weekday") or event_entry.get("vague_weekday")
    weekday_label = _weekday_label_from_dates(sample_dates, _pluralize_weekday_hint(weekday_hint_value))
    if week_scope:
        weekday_label = None
    if day_line and month_for_line and day_year:
        message_lines.append("")
        if week_scope:
            message_lines.append(
                f"Dates available in {_format_label_text(week_scope['label'])} {day_year}: {day_line}"
            )
        else:
            label_prefix = weekday_label or "Dates"
            message_lines.append(f"{label_prefix} available in {_format_label_text(month_for_line)} {day_year}: {day_line}")
        message_lines.append("")

    message_lines.extend(["", "AVAILABLE DATES:"])
    if formatted_dates:
        for iso_value in formatted_dates[:5]:
            message_lines.append(f"- {iso_value} {slot_text}")
    else:
        message_lines.append("- No suitable slots within the next 45 days.")

    next_step_lines = ["", "NEXT STEP:"]
    if future_display:
        next_step_lines.append(f"Say yes if {future_display} works and I'll pencil it in so we can move straight into Room Availability.")
        next_step_lines.append("Prefer another option? Share a different day or time and I'll check availability.")
    elif week_scope:
        next_step_lines.append("Tell me which date works best so I can move to Room Availability and shortlist the best rooms.")
    else:
        next_step_lines.append("Tell me which date works best so I can move to Room Availability and shortlist the best rooms.")
        next_step_lines.append("Or share another day/time and I'll check availability.")
    message_lines.extend(next_step_lines)
    prompt = "\n".join(message_lines)

    weekday_hint = weekday_hint_value
    time_hint = state.user_info.get("vague_time_of_day") or event_entry.get("vague_time_of_day")
    time_display = str(time_hint).strip().capitalize() if time_hint else slot_text
    table_rows: List[Dict[str, Any]] = []
    actions_payload: List[Dict[str, Any]] = []
    for iso_value in formatted_dates[:5]:
        display_date = format_iso_date_to_ddmmyyyy(iso_value) or iso_value
        table_rows.append(
            {
                "iso_date": iso_value,
                "display_date": display_date,
                "time_of_day": time_display,
            }
        )
        actions_payload.append(
            {
                "type": "select_date",
                "label": f"{display_date} ({time_display})",
                "date": iso_value,
                "display_date": display_date,
            }
        )

    if weekday_label and month_for_line:
        label_base = f"{weekday_label} in {_format_label_text(month_for_line)}"
    elif month_for_line:
        label_base = f"Dates in {_format_label_text(month_for_line)}"
    else:
        label_base = "Candidate dates"
    if time_hint:
        label_base = f"{label_base} ({time_display})"

    _trace_candidate_gate(_thread_id(state), formatted_dates[:5])

    draft_message = {
        "body": prompt,
        "body_markdown": prompt,
        "step": 2,
        "next_step": "Room Availability",
        "topic": "date_candidates",
        "candidate_dates": [format_iso_date_to_ddmmyyyy(iso) or iso for iso in formatted_dates[:5]],
        "table_blocks": [
            {
                "type": "dates",
                "label": label_base,
                "rows": table_rows,
            }
        ] if table_rows else [],
        "actions": actions_payload,
        "headers": [date_header_label],
    }
    if actions_payload:
        event_entry["candidate_dates"] = [action["date"] for action in actions_payload]
    state.add_draft_message(draft_message)

    update_event_metadata(event_entry, thread_state="Awaiting Client Response", current_step=2)
    write_stage(event_entry, current_step=WorkflowStep.STEP_2, subflow_group="date_confirmation")
    state.set_thread_state("Awaiting Client Response")
    state.extras["persist"] = True
    _emit_step2_snapshot(
        state,
        event_entry,
        extra={
            "candidate_dates": formatted_dates[:5],
            "slot_text": slot_text,
        },
    )

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "candidate_dates": formatted_dates[:5],
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
        "answered_question_first": True,
    }
    gatekeeper = refresh_gatekeeper(event_entry)
    state.telemetry.answered_question_first = True
    state.telemetry.gatekeeper_passed = dict(gatekeeper)
    payload["gatekeeper_passed"] = dict(gatekeeper)
    return GroupResult(action="date_options_proposed", payload=payload, halt=True)


def _iso_date_is_past(iso_value: str) -> bool:
    try:
        return datetime.fromisoformat(iso_value).date() < date.today()
    except ValueError:
        return True


def _safe_parse_iso_date(iso_value: str) -> Optional[date]:
    try:
        return datetime.fromisoformat(iso_value).date()
    except ValueError:
        return None


def _window_payload(window: ConfirmationWindow) -> Dict[str, Any]:
    return {
        "display_date": window.display_date,
        "iso_date": window.iso_date,
        "start_time": window.start_time,
        "end_time": window.end_time,
        "start_iso": window.start_iso,
        "end_iso": window.end_iso,
        "inherited_times": window.inherited_times,
        "partial": window.partial,
        "source_message_id": window.source_message_id,
    }


def _window_from_payload(payload: Dict[str, Any]) -> Optional[ConfirmationWindow]:
    if not isinstance(payload, dict):
        return None
    try:
        return ConfirmationWindow(
            display_date=payload.get("display_date"),
            iso_date=payload.get("iso_date"),
            start_time=payload.get("start_time"),
            end_time=payload.get("end_time"),
            start_iso=payload.get("start_iso"),
            end_iso=payload.get("end_iso"),
            inherited_times=bool(payload.get("inherited_times")),
            partial=bool(payload.get("partial")),
            source_message_id=payload.get("source_message_id"),
        )
    except TypeError:
        return None


def _format_window(window: ConfirmationWindow) -> str:
    if window.start_time and window.end_time:
        return f"{window.display_date} {window.start_time}–{window.end_time}"
    return window.display_date


def _is_affirmative_reply(text: str) -> bool:
    normalized = text.strip().lower()
    if not normalized:
        return False
    if normalized in AFFIRMATIVE_TOKENS:
        return True
    negative_prefixes = ("can you", "could you", "would you", "please", "may you")
    for token in AFFIRMATIVE_TOKENS:
        if token in normalized:
            if any(prefix in normalized for prefix in negative_prefixes) and "?" in normalized:
                continue
            return True
    return False


def _message_signals_confirmation(text: str) -> bool:
    normalized = text.strip().lower()
    if not normalized:
        return False
    if _is_affirmative_reply(normalized):
        return True
    for keyword in CONFIRMATION_KEYWORDS:
        if keyword in normalized:
            if "?" in normalized and any(prefix in normalized for prefix in ("can you", "could you")):
                continue
            return True
    return False


def _message_mentions_new_date(text: str) -> bool:
    if not text.strip():
        return False
    detected = parse_first_date(text, fallback_year=datetime.utcnow().year)
    return detected is not None


def _should_auto_accept_first_date(event_entry: dict) -> bool:
    requested_window = event_entry.get("requested_window") or {}
    if requested_window.get("hash"):
        return False
    if event_entry.get("pending_date_confirmation"):
        return False
    if event_entry.get("chosen_date") and event_entry.get("date_confirmed"):
        return False
    return True


def _reference_date_from_state(state: WorkflowState) -> date:
    ts = state.message.ts
    if ts:
        try:
            return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).date()
        except ValueError:
            pass
    return date.today()


def _preferred_room(event_entry: dict) -> str | None:
    """[Trigger] Helper to extract preferred room from requirements."""

    requirements = event_entry.get("requirements") or {}
    return requirements.get("preferred_room")


def _resolve_confirmation_window(state: WorkflowState, event_entry: dict) -> Optional[ConfirmationWindow]:
    """Resolve the requested window from the latest client message."""

    user_info = state.user_info or {}
    body_text = state.message.body or ""
    subject_text = state.message.subject or ""

    display_date, iso_date = _determine_date(user_info, body_text, subject_text, event_entry)
    if not display_date or not iso_date:
        return None

    start_time = _normalize_time_value(user_info.get("start_time"))
    end_time = _normalize_time_value(user_info.get("end_time"))

    inherited_times = False

    if not (start_time and end_time):
        parsed_start, parsed_end, matched = parse_time_range(body_text)
        if parsed_start and parsed_end:
            start_time = f"{parsed_start.hour:02d}:{parsed_start.minute:02d}"
            end_time = f"{parsed_end.hour:02d}:{parsed_end.minute:02d}"
        elif matched and not start_time:
            start_time = None

    if not (start_time and end_time):
        fallback = _existing_time_window(event_entry, iso_date)
        if fallback:
            start_time, end_time = fallback
            inherited_times = True

    partial = not (start_time and end_time)
    start_iso = end_iso = None
    if start_time and end_time:
        start_iso, end_iso = build_window_iso(iso_date, _to_time(start_time), _to_time(end_time))

    return ConfirmationWindow(
        display_date=display_date,
        iso_date=iso_date,
        start_time=start_time,
        end_time=end_time,
        start_iso=start_iso,
        end_iso=end_iso,
        inherited_times=inherited_times,
        partial=partial,
        source_message_id=state.message.msg_id,
    )


def _determine_date(
    user_info: Dict[str, Optional[str]],
    body_text: str,
    subject_text: str,
    event_entry: dict,
) -> Tuple[Optional[str], Optional[str]]:
    """Determine the DD.MM.YYYY and ISO representations for the confirmed date."""

    user_event_date = user_info.get("event_date")
    if user_event_date and is_valid_ddmmyyyy(user_event_date):
        iso_value = to_iso_date(user_event_date)
        if iso_value:
            return user_event_date, iso_value

    iso_candidate = user_info.get("date")
    if iso_candidate:
        ddmmyyyy = format_iso_date_to_ddmmyyyy(iso_candidate)
        if ddmmyyyy and is_valid_ddmmyyyy(ddmmyyyy):
            return ddmmyyyy, iso_candidate

    parsed = parse_first_date(body_text) or parse_first_date(subject_text)
    if parsed:
        return parsed.strftime("%d.%m.%Y"), parsed.isoformat()

    pending = event_entry.get("pending_time_request") or {}
    if pending.get("display_date") and pending.get("iso_date"):
        return pending["display_date"], pending["iso_date"]

    chosen_date = event_entry.get("chosen_date")
    if chosen_date and is_valid_ddmmyyyy(chosen_date):
        iso_value = to_iso_date(chosen_date)
        if iso_value:
            return chosen_date, iso_value
    return None, None


def _normalize_time_value(value: Optional[str]) -> Optional[str]:
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
        parsed = datetime.strptime(text, "%H:%M").time()
    except ValueError:
        return None
    return f"{parsed.hour:02d}:{parsed.minute:02d}"


def _existing_time_window(event_entry: dict, iso_date: str) -> Optional[Tuple[str, str]]:
    """Locate the last known window associated with the same date."""

    requested = event_entry.get("requested_window") or {}
    if requested.get("date_iso") == iso_date:
        start = _normalize_time_value(requested.get("start_time"))
        end = _normalize_time_value(requested.get("end_time"))
        if start and end:
            return start, end

    requirements = event_entry.get("requirements") or {}
    duration = requirements.get("event_duration") or {}
    start = _normalize_time_value(duration.get("start"))
    end = _normalize_time_value(duration.get("end"))
    if start and end:
        return start, end

    event_data = event_entry.get("event_data") or {}
    start = _normalize_time_value(event_data.get("Start Time"))
    end = _normalize_time_value(event_data.get("End Time"))
    if start and end:
        return start, end

    pending = event_entry.get("pending_time_request") or {}
    if pending.get("iso_date") == iso_date:
        start = _normalize_time_value(pending.get("start_time"))
        end = _normalize_time_value(pending.get("end_time"))
        if start and end:
            return start, end
    return None


def _handle_partial_confirmation(
    state: WorkflowState,
    event_entry: dict,
    window: ConfirmationWindow,
) -> GroupResult:
    """Persist the date and request a time clarification without stalling the flow."""

    event_entry.setdefault("event_data", {})["Event Date"] = window.display_date
    _set_pending_time_state(event_entry, window)

    state.user_info["event_date"] = window.display_date
    state.user_info["date"] = window.iso_date

    prompt = _with_greeting(
        state,
        f"Noted {window.display_date}. Preferred time? Examples: 14–18, 18–22.",
    )
    state.add_draft_message({"body": prompt, "step": 2, "topic": "date_time_clarification"})

    update_event_metadata(
        event_entry,
        chosen_date=window.display_date,
        date_confirmed=False,
        thread_state="Awaiting Client Response",
        current_step=2,
    )
    write_stage(event_entry, current_step=WorkflowStep.STEP_2, subflow_group="date_confirmation")

    state.set_thread_state("Awaiting Client Response")
    state.extras["persist"] = True
    _emit_step2_snapshot(
        state,
        event_entry,
        extra={
            "pending_time": True,
            "proposed_date": window.display_date,
        },
    )

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "pending_time": True,
        "event_date": window.display_date,
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
        "answered_question_first": True,
    }
    gatekeeper = refresh_gatekeeper(event_entry)
    state.telemetry.answered_question_first = True
    state.telemetry.gatekeeper_passed = dict(gatekeeper)
    payload["gatekeeper_passed"] = dict(gatekeeper)
    return GroupResult(action="date_time_clarification", payload=payload, halt=True)


def _prompt_confirmation(
    state: WorkflowState,
    event_entry: dict,
    window: ConfirmationWindow,
) -> GroupResult:
    formatted_window = _format_window(window)
    lines = [
        "INFO:",
        f"- {formatted_window} is available on our side. Shall I continue?",
        "",
        "NEXT STEP:",
        "- Reply \"yes\" to continue with Room Availability.",
        "- Or share another day/time and I'll check again.",
    ]
    prompt = _with_greeting(state, "\n".join(lines))

    draft_message = {
        "body": prompt,
        "step": 2,
        "topic": "date_confirmation_pending",
        "proposed_date": window.display_date,
        "proposed_time": f"{window.start_time or ''}–{window.end_time or ''}".strip("–"),
    }
    state.add_draft_message(draft_message)

    update_event_metadata(
        event_entry,
        current_step=2,
        thread_state="Awaiting Client Response",
        date_confirmed=False,
    )
    write_stage(event_entry, current_step=WorkflowStep.STEP_2, subflow_group="date_confirmation")
    state.set_thread_state("Awaiting Client Response")
    state.extras["persist"] = True
    _emit_step2_snapshot(
        state,
        event_entry,
        extra={
            "pending_confirmation": True,
            "proposed_date": window.display_date,
        },
    )

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "pending_confirmation": True,
        "proposed_date": window.iso_date,
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
        "answered_question_first": True,
    }
    gatekeeper = refresh_gatekeeper(event_entry)
    payload["gatekeeper_passed"] = dict(gatekeeper)
    state.telemetry.answered_question_first = True
    state.telemetry.gatekeeper_passed = dict(gatekeeper)
    return GroupResult(action="date_confirmation_pending", payload=payload, halt=True)


def _finalize_confirmation(
    state: WorkflowState,
    event_entry: dict,
    window: ConfirmationWindow,
) -> GroupResult:
    """Persist the requested window and trigger availability."""

    thread_id = _thread_id(state)
    if isinstance(window, str):
        try:
            parsed_date = datetime.strptime(window, "%Y-%m-%d")
            display_date = parsed_date.strftime("%d.%m.%Y")
            iso_date = window
        except ValueError:
            display_date = window
            iso_date = to_iso_date(window) or window
        fallback_window = event_entry.get("requested_window") or {}
        start_time = fallback_window.get("start_time")
        end_time = fallback_window.get("end_time")
        start_iso = fallback_window.get("start")
        end_iso = fallback_window.get("end")
        window = ConfirmationWindow(
            display_date=display_date,
            iso_date=iso_date,
            start_time=start_time,
            end_time=end_time,
            start_iso=start_iso,
            end_iso=end_iso,
            inherited_times=bool(start_time and end_time),
            partial=not (start_time and end_time),
            source_message_id=fallback_window.get("source_message_id"),
        )

    state.event_id = event_entry.get("event_id")
    tag_message(event_entry, window.source_message_id)
    event_entry.setdefault("event_data", {})["Event Date"] = window.display_date
    event_entry["event_data"]["Start Time"] = window.start_time
    event_entry["event_data"]["End Time"] = window.end_time

    requirements = dict(event_entry.get("requirements") or {})
    requirements["event_duration"] = {"start": window.start_time, "end": window.end_time}
    new_req_hash = requirements_hash(requirements)

    state.user_info["event_date"] = window.display_date
    state.user_info["date"] = window.iso_date
    state.user_info["start_time"] = window.start_time
    state.user_info["end_time"] = window.end_time

    previous_window = event_entry.get("requested_window") or {}
    new_hash = _window_hash(window.iso_date, window.start_iso, window.end_iso)
    reuse_previous = previous_window.get("hash") == new_hash

    requested_payload = {
        "display_date": window.display_date,
        "date_iso": window.iso_date,
        "start_time": window.start_time,
        "end_time": window.end_time,
        "start": window.start_iso,
        "end": window.end_iso,
        "tz": "Europe/Zurich",
        "hash": new_hash,
        "times_inherited": window.inherited_times,
        "source_message_id": window.source_message_id,
        "updated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "cached": reuse_previous,
    }
    event_entry["requested_window"] = requested_payload
    event_entry.pop("pending_time_request", None)

    update_event_metadata(
        event_entry,
        chosen_date=window.display_date,
        date_confirmed=True,
        requirements=requirements,
        requirements_hash=new_req_hash,
        thread_state="In Progress",
    )
    if not reuse_previous:
        update_event_metadata(
            event_entry,
            room_eval_hash=None,
            locked_room_id=None,
        )

    caller_step = event_entry.get("caller_step")
    next_step = caller_step if caller_step else 3

    _emit_step2_snapshot(
        state,
        event_entry,
        extra={
            "confirmed_date": window.display_date,
            "date_confirmed": True,
        },
    )
    append_audit_entry(event_entry, 2, next_step, "date_confirmed")
    update_event_metadata(event_entry, current_step=next_step, caller_step=None)
    try:
        next_stage = WorkflowStep(f"step_{next_step}")
    except ValueError:
        next_stage = WorkflowStep.STEP_3
    write_stage(event_entry, current_step=next_stage, subflow_group=default_subflow(next_stage))

    if state.client and state.event_id:
        link_event_to_client(state.client, state.event_id)

    _record_confirmation_log(event_entry, state, window, reuse_previous)

    state.set_thread_state("In Progress")
    state.current_step = next_step
    state.caller_step = None
    state.subflow_group = default_subflow(next_stage)
    state.extras["persist"] = True

    payload = {
        "client_id": state.client_id,
        "event_id": state.event_id,
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "event_date": window.display_date,
        "requested_window": requested_payload,
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "next_step": next_step,
        "cache_reused": reuse_previous,
        "context": state.context_snapshot,
        "persisted": True,
        "answered_question_first": True,
    }
    payload["actions"] = [{"type": "send_reply"}]
    gatekeeper = refresh_gatekeeper(event_entry)
    state.telemetry.answered_question_first = True
    state.telemetry.gatekeeper_passed = dict(gatekeeper)
    payload["gatekeeper_passed"] = dict(gatekeeper)
    state.intent_detail = "event_update"

    promote_fields(
        state,
        event_entry,
        {
            ("date",): window.iso_date,
            ("event_date",): window.display_date,
            ("start_time",): window.start_time,
            ("end_time",): window.end_time,
        },
        remove_deferred=["date_confirmation"],
    )

    autorun_failed = False
    if next_step == 3:
        try:
            from backend.workflows.groups.room_availability.trigger.process import process as room_process

            room_result = room_process(state)
            if isinstance(room_result.payload, dict):
                room_result.payload.setdefault("confirmed_date", window.display_date)
                room_result.payload.setdefault("gatekeeper_passed", dict(gatekeeper))
            return room_result
        except Exception as exc:  # pragma: no cover - defensive guard
            autorun_failed = True
            state.extras["room_autorun_failed"] = True
            payload["room_autorun_failed"] = True
            trace_marker(
                thread_id,
                "STEP3_AUTORUN_FAILED",
                detail=str(exc),
                data={
                    "type": exc.__class__.__name__,
                    "event_id": state.event_id,
                },
                owner_step="Step2_Date",
            )

    participants = _extract_participants_from_state(state)
    noted_line = (
        f"Noted: {participants} guests and {window.display_date}."
        if participants
        else f"Noted: {window.display_date} is confirmed."
    )
    follow_up_line = "I'll move straight into Room Availability and send the best-fitting rooms."
    ack_body, ack_headers = format_sections_with_headers(
        [("Next step", [noted_line, follow_up_line])]
    )
    state.add_draft_message(
        {
            "body": ack_body,
            "body_markdown": ack_body,
            "step": next_step,
            "topic": "date_confirmed",
            "headers": ack_headers,
        }
    )
    if autorun_failed:
        return GroupResult(action="date_confirmed", payload=payload, halt=False)
    return GroupResult(action="date_confirmed", payload=payload, halt=True)


def _record_confirmation_log(
    event_entry: dict,
    state: WorkflowState,
    window: ConfirmationWindow,
    reused: bool,
) -> None:
    logs = event_entry.setdefault("logs", [])
    details = {
        "intent": state.intent.value if state.intent else None,
        "requested_window": {
            "date": window.iso_date,
            "start": window.start_iso,
            "end": window.end_iso,
            "tz": "Europe/Zurich",
        },
        "times_inherited": window.inherited_times,
        "source_message_id": window.source_message_id,
        "reused": reused,
    }
    logs.append(
        {
            "ts": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "actor": "workflow",
            "action": "date_confirmed",
            "details": details,
        }
    )


def _window_hash(date_iso: str, start_iso: Optional[str], end_iso: Optional[str]) -> str:
    payload = f"{date_iso}|{start_iso or ''}|{end_iso or ''}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _to_time(value: str) -> time:
    return datetime.strptime(value, "%H:%M").time()


def _set_pending_time_state(event_entry: dict, window: ConfirmationWindow) -> None:
    event_entry["pending_time_request"] = {
        "display_date": window.display_date,
        "iso_date": window.iso_date,
        "start_time": window.start_time,
        "end_time": window.end_time,
        "source_message_id": window.source_message_id,
        "created_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    }


def _trace_candidate_gate(thread_id: str, candidates: List[str]) -> None:
    if not thread_id:
        return
    count = len([value for value in candidates if value])
    if count == 0:
        label = "feasible=0"
    elif count == 1:
        label = "feasible=1"
    else:
        label = "feasible=many"
    trace_gate(thread_id, "Step2_Date", label, True, {"count": count})


def _message_text(state: WorkflowState) -> str:
    message = state.message
    if not message:
        return ""
    subject = message.subject or ""
    body = message.body or ""
    if subject and body:
        return f"{subject}\n{body}"
    return subject or body


def _build_select_date_action(date_value: dt.date, ddmmyyyy: str, time_label: Optional[str]) -> Dict[str, Any]:
    label = date_value.strftime("%a %d %b %Y")
    if time_label:
        label = f"{label} · {time_label}"
    return {
        "type": "select_date",
        "label": f"Confirm {label}",
        "date": ddmmyyyy,
        "iso_date": date_value.isoformat(),
    }


def _format_time_label(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    lowered = raw.strip().lower()
    if not lowered:
        return None
    return lowered.capitalize()


def _format_room_availability(entries: List[Dict[str, Any]]) -> List[str]:
    grouped: Dict[str, List[Tuple[str, str]]] = {}
    for entry in entries:
        room = str(entry.get("room") or "Room").strip() or "Room"
        date_label = entry.get("date_label") or entry.get("iso_date") or ""
        status = entry.get("status") or "Available"
        grouped.setdefault(room, []).append((date_label, status))

    lines: List[str] = []
    for room, values in grouped.items():
        seen: set[Tuple[str, str]] = set()
        formatted: List[str] = []
        for date_label, status in values:
            if not date_label:
                continue
            key = (date_label, status)
            if key in seen:
                continue
            seen.add(key)
            label = date_label
            if status and status.lower() not in {"available"}:
                label = f"{date_label} ({status})"
            formatted.append(label)
        if formatted:
            lines.append(f"{room} — Available on: {', '.join(formatted)}")
    return lines


def _compact_products_summary(preferences: Dict[str, Any]) -> List[str]:
    lines = ["Products & Catering (summary):"]
    wish_products = []
    raw_wishes = preferences.get("wish_products") if isinstance(preferences, dict) else None
    if isinstance(raw_wishes, (list, tuple)):
        wish_products = [str(item).strip() for item in raw_wishes if str(item).strip()]
    if wish_products:
        highlights = ", ".join(wish_products[:3])
        lines.append(f"- Highlights: {highlights}.")
    else:
        lines.append("- Seasonal menus with flexible wine pairings available.")
    return lines


def _user_requested_products(state: WorkflowState, classification: Dict[str, Any]) -> bool:
    message_text = (_message_text(state) or "").lower()
    if any(keyword in message_text for keyword in ("menu", "cater", "product", "wine")):
        return True
    parsed = classification.get("parsed") or {}
    if isinstance(parsed, dict):
        if parsed.get("products") or parsed.get("catering"):
            return True
    return False


def _resolve_window_hints(constraints: Dict[str, Any], state: WorkflowState) -> WindowHints:
    user_info = state.user_info or {}
    event_entry = state.event_entry or {}
    month_hint = constraints.get("vague_month") or user_info.get("vague_month") or event_entry.get("vague_month")
    weekday_hint = constraints.get("weekday") or user_info.get("vague_weekday") or event_entry.get("vague_weekday")
    time_of_day = (
        constraints.get("time_of_day")
        or user_info.get("vague_time_of_day")
        or event_entry.get("vague_time_of_day")
    )
    return month_hint, weekday_hint, time_of_day


def _is_weekend_token(token: Optional[Any]) -> bool:
    if token is None:
        return False
    if isinstance(token, (list, tuple, set)):
        return any(_is_weekend_token(item) for item in token)
    normalized = str(token).strip().lower()
    if not normalized:
        return False
    return normalized.startswith("sat") or normalized.startswith("sun") or "weekend" in normalized


def _resolve_week_scope(state: WorkflowState, reference_day: date) -> Optional[Dict[str, Any]]:
    user_info = state.user_info or {}
    event_entry = state.event_entry or {}
    window_scope: Dict[str, Any] = {}
    for candidate in (event_entry.get("window_scope"), user_info.get("window")):
        if isinstance(candidate, dict):
            window_scope.update(candidate)

    month_hint = (
        window_scope.get("month")
        or user_info.get("vague_month")
        or event_entry.get("vague_month")
    )
    week_index = (
        window_scope.get("week_index")
        or user_info.get("week_index")
        or event_entry.get("week_index")
    )
    weekdays_hint = (
        window_scope.get("weekdays_hint")
        or user_info.get("weekdays_hint")
        or event_entry.get("weekdays_hint")
    )
    weekday_token = (
        window_scope.get("weekday")
        or user_info.get("vague_weekday")
        or event_entry.get("vague_weekday")
    )

    if not month_hint or (week_index is None and not weekdays_hint):
        return None

    include_weekends = _is_weekend_token(weekday_token)
    dates = from_hints(
        month=month_hint,
        week_index=week_index,
        weekdays_hint=weekdays_hint if isinstance(weekdays_hint, (list, tuple, set)) else None,
        reference=reference_day,
        mon_fri_only=not include_weekends,
    )
    if not dates:
        return None
    try:
        first_day = datetime.fromisoformat(dates[0])
    except ValueError:
        return None
    derived_week_index = ((first_day.day - 1) // 7) + 1
    month_index = _MONTH_NAME_TO_INDEX.get(str(month_hint).strip().lower())
    if month_index is None:
        month_index = first_day.month
    month_label = window_scope.get("month") or MONTH_INDEX_TO_NAME.get(month_index, _format_label_text(month_hint))
    label = f"Week {derived_week_index} of {month_label}"
    return {
        "dates": dates,
        "week_index": derived_week_index,
        "month_label": month_label,
        "label": label,
        "weekdays_hint": list(weekdays_hint) if isinstance(weekdays_hint, (list, tuple, set)) else [],
    }


def _has_window_constraints(window_hints: WindowHints) -> bool:
    month_hint, weekday_hint, _ = window_hints
    if month_hint:
        return True
    if isinstance(weekday_hint, (list, tuple, set)):
        return any(bool(item) for item in weekday_hint)
    return bool(weekday_hint)


def _format_label_text(label: Optional[Any]) -> str:
    if label is None:
        return ""
    text = str(label).strip()
    if not text:
        return ""
    if text.lower() == text:
        return text.capitalize()
    return text


def _date_header_label(month_hint: Optional[str], week_label: Optional[str] = None) -> str:
    if week_label:
        return f"Date options for {_format_label_text(week_label)}"
    if month_hint:
        return f"Date options for {_format_label_text(month_hint)}"
    return "Date options"


def _format_day_list(iso_dates: Sequence[str]) -> Tuple[str, Optional[int]]:
    if not iso_dates:
        return "", None
    day_labels: List[str] = []
    year_value: Optional[int] = None
    for iso_value in iso_dates:
        try:
            parsed = datetime.fromisoformat(iso_value)
        except ValueError:
            continue
        day_labels.append(parsed.strftime("%d"))
        year_value = year_value or parsed.year
    return ", ".join(day_labels), year_value


_WEEKDAY_LABELS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


def _weekday_label_from_dates(
    iso_dates: Sequence[str],
    fallback: Optional[str] = None,
) -> Optional[str]:
    counts: Counter[int] = Counter()
    for iso_value in iso_dates:
        try:
            parsed = datetime.fromisoformat(iso_value)
        except ValueError:
            continue
        counts.update([parsed.weekday()])
    if counts:
        weekday_index, _ = counts.most_common(1)[0]
        base = _WEEKDAY_LABELS[weekday_index]
        return f"{base}s"
    return fallback


def _month_label_from_dates(
    iso_dates: Sequence[str],
    fallback: Optional[str] = None,
) -> Optional[str]:
    for iso_value in iso_dates:
        try:
            parsed = datetime.fromisoformat(iso_value)
        except ValueError:
            continue
        return parsed.strftime("%B")
    return fallback


def _pluralize_weekday_hint(weekday_hint: Any) -> Optional[str]:
    if isinstance(weekday_hint, str):
        token = weekday_hint.strip()
        if token:
            label = token.capitalize()
            return f"{label}s" if not label.endswith("s") else label
    return None


def _maybe_general_qa_payload(state: WorkflowState) -> Optional[Dict[str, Any]]:
    event_entry = state.event_entry or {}
    user_info = state.user_info or {}
    month_hint = user_info.get("vague_month") or event_entry.get("vague_month")
    message_text = _message_text(state)
    return build_menu_payload(message_text, context_month=month_hint)


_TIME_HINT_DEFAULTS = {
    "morning": ("08:00", "12:00"),
    "afternoon": ("12:00", "17:00"),
    "evening": ("18:00", "22:00"),
}


def _maybe_complete_from_time_hint(
    window: ConfirmationWindow,
    state: WorkflowState,
    event_entry: Dict[str, Any],
) -> Optional[ConfirmationWindow]:
    hint = state.user_info.get("vague_time_of_day") or event_entry.get("vague_time_of_day")
    if not hint:
        return None
    defaults = _TIME_HINT_DEFAULTS.get(str(hint).lower())
    if not defaults:
        return None
    try:
        start_iso, end_iso = build_window_iso(
            window.iso_date,
            _to_time(defaults[0]),
            _to_time(defaults[1]),
        )
    except ValueError:
        return None
    return ConfirmationWindow(
        display_date=window.display_date,
        iso_date=window.iso_date,
        start_time=defaults[0],
        end_time=defaults[1],
        start_iso=start_iso,
        end_iso=end_iso,
        inherited_times=True,
        partial=False,
        source_message_id=window.source_message_id,
    )


def _normalize_month_token(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    token = str(value).strip().lower()
    return _MONTH_NAME_TO_INDEX.get(token)


def _normalize_weekday_tokens(value: Any) -> List[int]:
    if value in (None, "", [], ()):
        return []
    if isinstance(value, (list, tuple, set)):
        tokens = [str(item).strip().lower() for item in value if str(item).strip()]
    else:
        tokens = [str(value).strip().lower()]
    indices: List[int] = []
    for token in tokens:
        idx = _WEEKDAY_NAME_TO_INDEX.get(token)
        if idx is not None:
            indices.append(idx)
    return sorted(set(indices))


def _window_filters(window_hints: WindowHints) -> Tuple[Optional[int], List[int]]:
    month_hint, weekday_hint, _ = window_hints
    return _normalize_month_token(month_hint), _normalize_weekday_tokens(weekday_hint)


def _describe_constraints(
    month_hint: Optional[str],
    weekday_hint: Optional[Any],
    time_of_day: Optional[str],
) -> str:
    parts: List[str] = []
    if weekday_hint:
        if isinstance(weekday_hint, (list, tuple, set)):
            tokens = [str(word).capitalize() for word in weekday_hint if str(word).strip()]
            if tokens:
                parts.append(", ".join(tokens))
        else:
            parts.append(str(weekday_hint).capitalize())
    if month_hint:
        parts.append(f"in {str(month_hint).capitalize()}")
    descriptor = " ".join(parts) if parts else "for your requested window"
    if time_of_day:
        descriptor += f" ({str(time_of_day).lower()})"
    return descriptor


def _extract_participants_from_state(state: WorkflowState) -> Optional[int]:
    candidates: List[Any] = []
    user_info = state.user_info or {}
    candidates.append(user_info.get("participants"))
    candidates.append(user_info.get("number_of_participants"))
    event_entry = state.event_entry or {}
    requirements = event_entry.get("requirements") or {}
    candidates.append(requirements.get("number_of_participants"))
    for raw in candidates:
        if raw in (None, "", "Not specified", "none"):
            continue
        try:
            return int(str(raw).strip().strip("~+"))
        except (TypeError, ValueError):
            continue
    return None


def _is_hybrid_availability_request(classification: Dict[str, Any], state: WorkflowState) -> bool:
    constraints = classification.get("constraints") or {}
    if any(constraints.get(key) for key in ("vague_month", "weekday", "time_of_day")):
        return True
    user_info = state.user_info or {}
    return bool(user_info.get("vague_month") or user_info.get("vague_weekday") or user_info.get("vague_time_of_day"))


def _candidate_dates_for_constraints(
    state: WorkflowState,
    constraints: Dict[str, Any],
    limit: int = 5,
    *,
    window_hints: Optional[WindowHints] = None,
    strict: bool = False,
) -> List[str]:
    hints = window_hints or _resolve_window_hints(constraints, state)
    month_hint, weekday_hint, _ = hints
    reference_day = _reference_date_from_state(state)
    rules: Dict[str, Any] = {"timezone": "Europe/Zurich"}
    if month_hint:
        rules["month"] = month_hint
    if isinstance(weekday_hint, list) and weekday_hint:
        rules["weekday"] = weekday_hint[0]
    elif isinstance(weekday_hint, str):
        rules["weekday"] = weekday_hint

    dates = next5(state.message.ts if state.message else None, rules)
    match_only = strict and _has_window_constraints(hints)
    iso_values: List[str] = []
    seen: set[str] = set()
    month_index, weekday_indices = _window_filters(hints)
    clamp_year: Optional[int] = None
    if month_index:
        clamp_year = reference_day.year
        days_in_month = monthrange(clamp_year, month_index)[1]
        if reference_day.month > month_index or (
            reference_day.month == month_index and reference_day.day > days_in_month
        ):
            clamp_year += 1

    for value in dates:
        if clamp_year:
            if value.year < clamp_year:
                continue
            if value.year > clamp_year:
                break
        iso_value = value.strftime("%Y-%m-%d")
        if iso_value in seen:
            continue
        if match_only:
            if month_index and value.month != month_index:
                continue
            if weekday_indices and value.weekday() not in weekday_indices:
                continue
        iso_values.append(iso_value)
        seen.add(iso_value)
        if len(iso_values) >= limit:
            break

    if not iso_values and not match_only:
        for value in dates:
            iso_value = value.strftime("%Y-%m-%d")
            if iso_value in seen:
                continue
            iso_values.append(iso_value)
            seen.add(iso_value)
            if len(iso_values) >= limit:
                break

    return iso_values[:limit]


def _format_general_availability(
    entries: List[Dict[str, Any]],
    participants: Optional[int],
) -> List[str]:
    if not entries:
        return []
    grouped: Dict[str, Dict[str, Any]] = {}
    for entry in entries:
        iso = entry.get("iso_date")
        if not iso:
            continue
        data = grouped.setdefault(
            iso,
            {"label": entry.get("date_label") or iso, "statuses": set()},
        )
        status = (entry.get("status") or "Available").lower()
        data["statuses"].add(status)
    pax_label = f"{participants} guests" if participants else "your group"
    lines: List[str] = []
    for iso in sorted(grouped.keys()):
        info = grouped[iso]
        statuses = info["statuses"]
        if "available" in statuses:
            qualifier = "Available"
        elif "option" in statuses:
            qualifier = "On option"
        else:
            qualifier = next(iter(statuses)).capitalize()
        lines.append(f"- {info['label']} — {qualifier} for {pax_label}")
        if len(lines) >= 4:
            break
    return lines


def _search_range_availability(
    state: WorkflowState,
    thread_id: Optional[str],
    constraints: Dict[str, Any],
    participants: Optional[int],
    preferences: Dict[str, Any],
    preferred_room: Optional[str],
) -> List[Dict[str, Any]]:
    window_hints = _resolve_window_hints(constraints, state)
    strict_window = _has_window_constraints(window_hints)
    iso_dates = _candidate_dates_for_constraints(
        state,
        constraints,
        window_hints=window_hints,
        strict=strict_window,
    )
    if not iso_dates:
        return []

    rooms = load_rooms()
    results: List[Dict[str, Any]] = []
    iso_seen: set[str] = set()
    limit = 5

    for iso_date in iso_dates:
        status_map = {room: room_status_on_date(state.db, iso_date, room) for room in rooms}
        ranked = rank_rooms(
            status_map,
            preferred_room=preferred_room,
            pax=participants,
            preferences=preferences,
        )
        for entry in ranked[:3]:
            results.append(
                {
                    "iso_date": iso_date,
                    "date_label": datetime.strptime(iso_date, "%Y-%m-%d").strftime("%a %d %b %Y"),
                    "room": entry.room,
                    "status": entry.status,
                    "hint": entry.hint,
                }
            )
        iso_seen.add(iso_date)
        if len(iso_seen) >= limit:
            break

    if thread_id:
        trace_db_read(
            thread_id,
            "Step2_Date",
            "db.rooms.search_range",
            {
                "constraints": {
                    "month": constraints.get("vague_month"),
                    "weekday": constraints.get("weekday"),
                    "time_of_day": constraints.get("time_of_day"),
                    "pax": participants,
                },
                "result_count": len(results),
                "sample": results[:3],
            },
        )

    return results[: limit * 3]


def _present_general_room_qna(
    state: WorkflowState,
    event_entry: dict,
    classification: Dict[str, Any],
    thread_id: Optional[str],
    qa_payload: Optional[Dict[str, Any]] = None,
) -> GroupResult:
    subloop_label = "general_q_a"
    state.extras["subloop"] = subloop_label
    resolved_thread_id = thread_id or state.thread_id
    constraints = classification.get("constraints") or {}
    if not isinstance(constraints, dict):
        constraints = {}
    participants = _extract_participants_from_state(state)
    user_preferences = {}
    if isinstance(state.user_info, dict):
        user_preferences = state.user_info.get("preferences") or {}
    if not user_preferences and isinstance(event_entry, dict):
        user_preferences = event_entry.get("preferences") or {}
    if not isinstance(user_preferences, dict):
        user_preferences = {}
    requirements = event_entry.get("requirements") if isinstance(event_entry, dict) else None
    preferred_room = None
    if isinstance(state.user_info, dict):
        preferred_room = state.user_info.get("preferred_room")
    if not preferred_room and isinstance(requirements, dict):
        preferred_room = requirements.get("preferred_room")
    range_results = _search_range_availability(
        state,
        resolved_thread_id,
        constraints,
        participants,
        user_preferences,
        preferred_room,
    )
    range_lookup: Dict[str, str] = {}
    for entry in range_results:
        iso_value = entry.get("iso_date")
        if not iso_value:
            continue
        try:
            parsed = datetime.fromisoformat(iso_value)
        except ValueError:
            continue
        label = parsed.strftime("%d.%m.%Y")
        range_lookup.setdefault(label, parsed.date().isoformat())
    range_candidate_dates = sorted(range_lookup.keys(), key=lambda lbl: range_lookup[lbl])[:5]
    range_actions = [
        {
            "type": "select_date",
            "label": f"Confirm {label}",
            "date": label,
            "iso_date": range_lookup[label],
        }
        for label in range_candidate_dates
    ]
    if qa_payload:
        state.turn_notes["general_qa"] = qa_payload
        trace_general_qa_status(
            resolved_thread_id,
            "payload_attached",
            {"has_payload": True, "range_results": len(range_results)},
        )
    else:
        trace_general_qa_status(
            resolved_thread_id,
            "payload_missing",
            {"has_payload": False, "range_results": len(range_results)},
        )
    if thread_id:
        set_subloop(thread_id, subloop_label)

    # MULTI-TURN FIX: Always run fresh extraction for each general_room_qna message
    # Store minimal "last_general_qna" context only for follow-up detection
    last_qna_context = event_entry.get("last_general_qna") if isinstance(event_entry, dict) else {}

    # Always extract fresh from current message
    message = state.message
    subject = (message.subject if message else "") or ""
    body = (message.body if message else "") or ""
    message_text = f"{subject}\n{body}".strip() or body or subject

    scan = state.extras.get("general_qna_scan")
    # Force fresh extraction (force_refresh=True) for multi-turn Q&A
    ensure_qna_extraction(state, message_text, scan, force_refresh=True)
    extraction = state.extras.get("qna_extraction")

    # Clear stale qna_cache AFTER extraction to prevent reuse of old extraction
    # (force_refresh=True prevents new cache from being saved)
    if isinstance(event_entry, dict):
        event_entry.pop("qna_cache", None)

    structured = build_structured_qna_result(state, extraction) if extraction else None

    if structured and structured.handled:
        rooms = structured.action_payload.get("db_summary", {}).get("rooms", [])
        date_lookup: Dict[str, str] = {}
        for entry in rooms:
            iso_date = entry.get("date") or entry.get("iso_date")
            if not iso_date:
                continue
            try:
                parsed = datetime.fromisoformat(iso_date)
            except ValueError:
                try:
                    parsed = datetime.strptime(iso_date, "%Y-%m-%d")
                except ValueError:
                    continue
            label = parsed.strftime("%d.%m.%Y")
            date_lookup.setdefault(label, parsed.date().isoformat())

        candidate_dates = sorted(date_lookup.keys(), key=lambda label: date_lookup[label])[:5]
        actions = [
            {
                "type": "select_date",
                "label": f"Confirm {label}",
                "date": label,
                "iso_date": date_lookup[label],
            }
            for label in candidate_dates
        ]

        body_markdown = (structured.body_markdown or _fallback_structured_body(structured.action_payload)).strip()
        footer_body = append_footer(
            body_markdown,
            step=2,
            next_step=3,
            thread_state="Awaiting Client",
        )

        draft_message = {
            "body": footer_body,
            "body_markdown": body_markdown,
            "step": 2,
            "next_step": 3,
            "thread_state": "Awaiting Client",
            "topic": "general_room_qna",
            "candidate_dates": candidate_dates,
            "actions": actions,
            "subloop": subloop_label,
            "headers": ["General Q&A"],
        }
        if not candidate_dates and range_candidate_dates:
            candidate_dates = range_candidate_dates
            actions = range_actions
            draft_message["candidate_dates"] = candidate_dates
            draft_message["actions"] = actions
        if range_results:
            draft_message["range_results"] = range_results

        state.add_draft_message(draft_message)
        update_event_metadata(
            event_entry,
            thread_state="Awaiting Client",
            current_step=2,
            candidate_dates=candidate_dates,
        )
        state.set_thread_state("Awaiting Client")
        state.record_subloop(subloop_label)
        state.intent_detail = "event_intake_with_question"
        state.extras["persist"] = True

        # Store minimal last_general_qna context for follow-up detection only
        if extraction and isinstance(event_entry, dict):
            q_values = extraction.get("q_values") or {}
            event_entry["last_general_qna"] = {
                "topic": structured.action_payload.get("qna_subtype"),
                "date_pattern": q_values.get("date_pattern"),
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }

        payload = {
            "client_id": state.client_id,
            "event_id": event_entry.get("event_id"),
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "candidate_dates": candidate_dates,
            "draft_messages": state.draft_messages,
            "thread_state": state.thread_state,
            "context": state.context_snapshot,
            "persisted": True,
            "general_qna": True,
            "structured_qna": structured.handled,
            "qna_select_result": structured.action_payload,
            "structured_qna_debug": structured.debug,
            "actions": actions,
        }
        if extraction:
            payload["qna_extraction"] = extraction
        return GroupResult(action="general_rooms_qna", payload=payload, halt=True)

    fallback_prompt = "[STRUCTURED_QNA_FALLBACK]\nI couldn't load the structured Q&A context for this request. Please review extraction logs."
    draft_message = {
        "step": 2,
        "topic": "general_room_qna",
        "body": f"{fallback_prompt}\n\n---\nStep: 2 Date Confirmation · Next: 3 Room Availability · State: Awaiting Client",
        "body_markdown": fallback_prompt,
        "next_step": 3,
        "thread_state": "Awaiting Client",
        "headers": ["General Q&A"],
        "requires_approval": False,
        "subloop": subloop_label,
        "actions": range_actions,
        "candidate_dates": range_candidate_dates,
    }
    if range_results:
        draft_message["range_results"] = range_results
    state.add_draft_message(draft_message)
    update_event_metadata(
        event_entry,
        thread_state="Awaiting Client",
        current_step=2,
        candidate_dates=[],
    )
    state.set_thread_state("Awaiting Client")
    state.record_subloop(subloop_label)
    state.intent_detail = "event_intake_with_question"
    state.extras["structured_qna_fallback"] = True
    structured_payload = structured.action_payload if structured else {}
    structured_debug = structured.debug if structured else {"reason": "missing_structured_context"}

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "candidate_dates": range_candidate_dates,
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
        "general_qna": True,
        "structured_qna": False,
        "structured_qna_fallback": True,
        "qna_select_result": structured_payload,
        "structured_qna_debug": structured_debug,
    }
    if extraction:
        payload["qna_extraction"] = extraction
    return GroupResult(action="general_rooms_qna", payload=payload, halt=True)
