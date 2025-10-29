from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, time
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
    capture_user_fields(state, current_step=2, source=state.message.msg_id)
    window = _resolve_confirmation_window(state, event_entry)
    if window is None:
        return _present_candidate_dates(state, event_entry)

    if window.partial:
        return _handle_partial_confirmation(state, event_entry, window)

    return _finalize_confirmation(state, event_entry, window)


def _present_candidate_dates(state: WorkflowState, event_entry: dict) -> GroupResult:
    """[Trigger] Provide five deterministic candidate dates to the client."""

    requirements = event_entry.get("requirements") or {}
    preferred_room = requirements.get("preferred_room") or "Not specified"
    # Prefer anchoring suggestions around any month/day mentioned in the latest message.
    user_text = f"{state.message.subject or ''} {state.message.body or ''}".strip()
    anchor = parse_first_date(user_text, fallback_year=datetime.utcnow().year)
    anchor_iso = anchor.isoformat() if anchor else state.message.ts
    candidate_dates: List[str] = suggest_dates(
        state.db,
        preferred_room=preferred_room,
        start_from_iso=anchor_iso,
        days_ahead=45,
        max_results=5,
    )
    if not candidate_dates:
        candidate_dates = []

    start_pref = _normalize_time_value(state.user_info.get("start_time")) or "18:00"
    end_pref = _normalize_time_value(state.user_info.get("end_time")) or "22:00"
    if start_pref and end_pref:
        slot_text = f"{start_pref}–{end_pref}"
    elif start_pref:
        slot_text = start_pref
    elif end_pref:
        slot_text = end_pref
    else:
        slot_text = "18:00–22:00"

    formatted_dates: List[str] = []
    for raw in candidate_dates:
        iso_value = to_iso_date(raw)
        formatted_dates.append(f"{iso_value or raw} {slot_text}".strip())

    message_lines = ["AVAILABLE DATES:"]
    if formatted_dates:
        message_lines.extend(f"- {entry}" for entry in formatted_dates)
    else:
        message_lines.append("- No suitable slots within the next 45 days.")
    message_lines.extend(
        [
            "",
            "NEXT STEP:",
            "Reply with the date that works best or share alternatives to check.",
        ]
    )
    prompt = "\n".join(message_lines)

    draft_message = {
        "body": prompt,
        "step": 2,
        "topic": "date_candidates",
        "candidate_dates": candidate_dates,
    }
    state.add_draft_message(draft_message)

    update_event_metadata(event_entry, thread_state="Awaiting Client Response", current_step=2)
    state.set_thread_state("Awaiting Client Response")
    state.extras["persist"] = True

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
        "answered_question_first": True,
    }
    gatekeeper = refresh_gatekeeper(event_entry)
    state.telemetry.answered_question_first = True
    state.telemetry.gatekeeper_passed = dict(gatekeeper)
    payload["gatekeeper_passed"] = dict(gatekeeper)
    return GroupResult(action="date_options_proposed", payload=payload, halt=True)


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

    prompt = f"Noted {window.display_date}. Preferred time? Examples: 14–18, 18–22."
    state.add_draft_message({"body": prompt, "step": 2, "topic": "date_time_clarification"})

    update_event_metadata(
        event_entry,
        chosen_date=window.display_date,
        date_confirmed=False,
        thread_state="Awaiting Client Response",
        current_step=2,
    )

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

    reply = compose_date_confirmation_reply(window.display_date, _preferred_room(event_entry))
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
