from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, time, date, timedelta
from typing import Dict, List, Optional, Tuple

from backend.workflows.common.datetime_parse import (
    build_window_iso,
    parse_first_date,
    parse_time_range,
    to_ddmmyyyy,
    to_iso_date,
)
from backend.workflows.common.capture import capture_user_fields, promote_fields
from backend.workflows.common.requirements import requirements_hash
from backend.workflows.common.gatekeeper import refresh_gatekeeper
from backend.workflows.common.timeutils import format_iso_date_to_ddmmyyyy
from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflows.groups.intake.condition.checks import suggest_dates
from backend.workflows.io.database import (
    append_audit_entry,
    link_event_to_client,
    tag_message,
    update_event_metadata,
)
from backend.utils.profiler import profile_step
from backend.services.availability import next_five_venue_dates, validate_window
from backend.workflow.state import WorkflowStep, default_subflow, write_stage

from ..condition.decide import is_valid_ddmmyyyy
from ..llm.analysis import compose_date_confirmation_reply

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


def _compose_greeting(state: WorkflowState) -> str:
    profile = (state.client or {}).get("profile", {}) if state.client else {}
    raw_name = profile.get("name") or state.message.from_name
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

    capture_user_fields(state, current_step=2, source=state.message.msg_id)

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

    window = _resolve_confirmation_window(state, event_entry)
    if window is None:
        return _present_candidate_dates(state, event_entry)

    if window.partial:
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

    auto_accept = _should_auto_accept_first_date(event_entry)
    if state.user_info.get("date") or state.user_info.get("event_date"):
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
    event_entry.pop("pending_future_confirmation", None)

    if fuzzy_candidates:
        seen_iso: set[str] = set()
        for iso_value in fuzzy_candidates:
            if iso_value in seen_iso or _iso_date_is_past(iso_value):
                continue
            seen_iso.add(iso_value)
            formatted_dates.append(iso_value)
    else:
        candidate_dates_ddmmyyyy: List[str] = suggest_dates(
            state.db,
            preferred_room=preferred_room,
            start_from_iso=anchor_dt.isoformat() if anchor_dt else state.message.ts,
            days_ahead=45,
            max_results=5,
        )

        seen_iso: set[str] = set()
        for raw in candidate_dates_ddmmyyyy:
            iso_value = to_iso_date(raw)
            if not iso_value:
                continue
            if _iso_date_is_past(iso_value) or iso_value in seen_iso:
                continue
            seen_iso.add(iso_value)
            formatted_dates.append(iso_value)

        if len(formatted_dates) < 5:
            skip = {_safe_parse_iso_date(iso) for iso in seen_iso}
            supplemental = next_five_venue_dates(anchor_dt, skip_dates={dt for dt in skip if dt is not None})
            for candidate in supplemental:
                if candidate in seen_iso:
                    continue
                seen_iso.add(candidate)
                formatted_dates.append(candidate)
                if len(formatted_dates) >= 5:
                    break

    if fuzzy_candidates:
        formatted_dates = formatted_dates[:4]

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

    message_lines.extend(["", "AVAILABLE DATES:"])
    if formatted_dates:
        for iso_value in formatted_dates[:5]:
            message_lines.append(f"- {iso_value} {slot_text}")
    else:
        message_lines.append("- No suitable slots within the next 45 days.")

    next_step_lines = ["", "NEXT STEP:"]
    if future_display:
        next_step_lines.append(f"Say yes if {future_display} works and I'll pencil it in.")
        next_step_lines.append("Prefer another option? Share a different day or time and I'll check availability.")
    else:
        next_step_lines.append("Tell me which date works best so I can continue with Date Confirmation.")
        next_step_lines.append("Or share another day/time and I'll check availability.")
    message_lines.extend(next_step_lines)
    prompt = "\n".join(message_lines)

    draft_message = {
        "body": prompt,
        "step": 2,
        "topic": "date_candidates",
        "candidate_dates": [format_iso_date_to_ddmmyyyy(iso) or iso for iso in formatted_dates[:5]],
    }
    state.add_draft_message(draft_message)

    update_event_metadata(event_entry, thread_state="Awaiting Client Response", current_step=2)
    write_stage(event_entry, current_step=WorkflowStep.STEP_2, subflow_group="date_confirmation")
    state.set_thread_state("Awaiting Client Response")
    state.extras["persist"] = True

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

    append_audit_entry(event_entry, 2, next_step, "date_confirmed")
    update_event_metadata(event_entry, current_step=next_step, caller_step=None)
    try:
        next_stage = WorkflowStep(f"step_{next_step}")
    except ValueError:
        next_stage = WorkflowStep.STEP_3
    write_stage(event_entry, current_step=next_stage, subflow_group=default_subflow(next_stage))

    reply = compose_date_confirmation_reply(window.display_date, _preferred_room(event_entry))
    reply = _with_greeting(state, reply)
    state.add_draft_message(
        {
            "body": reply,
            "step": 2,
            "topic": "date_confirmation",
            "date": window.display_date,
        }
    )

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
    gatekeeper = refresh_gatekeeper(event_entry)
    state.telemetry.answered_question_first = True
    state.telemetry.gatekeeper_passed = dict(gatekeeper)
    payload["gatekeeper_passed"] = dict(gatekeeper)

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
    return GroupResult(action="date_confirmed", payload=payload)


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
