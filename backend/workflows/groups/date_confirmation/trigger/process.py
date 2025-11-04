from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import List, Optional, Tuple

from backend.workflows.common.datetime_parse import (
    TZ_ZURICH,
    enumerate_month_weekday,
    month_name_to_number,
    weekday_name_to_number,
)
from backend.workflows.common.prompts import append_footer
from backend.workflows.common.timeutils import format_iso_date_to_ddmmyyyy
from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflows.groups.intake.condition.checks import blackout_days, suggest_dates
from backend.workflows.groups.intake.condition.checks import room_status_on_date
from backend.debug.hooks import trace_db_read, trace_db_write, trace_gate, trace_state, trace_step
from backend.workflows.io.database import append_audit_entry, link_event_to_client, tag_message, update_event_metadata
from backend.utils.profiler import profile_step

from ..condition.decide import is_valid_ddmmyyyy
from ..llm.analysis import compose_date_confirmation_reply

__workflow_role__ = "trigger"


@dataclass
class ConfirmationWindow:
    display_date: Optional[str]
    iso_date: Optional[str]
    start_time: Optional[str]
    end_time: Optional[str]
    start_iso: Optional[str]
    end_iso: Optional[str]
    inherited_times: bool = False
    partial: bool = False
    source_message_id: Optional[str] = None
    tz: str = "Europe/Zurich"


@dataclass
class DateProposal:
    body_lines: List[str]
    candidate_dates: List[str]
    table_blocks: List[dict]
    actions: List[dict]
    topic: str = "date_candidates"


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
    chosen_date = event_entry.get("chosen_date")
    if not chosen_date:
        return _present_candidate_dates(state, event_entry)

    confirmed_date = _resolve_confirmed_date(state)
    if not confirmed_date:
        return _present_candidate_dates(state, event_entry)

    return _finalize_confirmation(state, event_entry, confirmed_date)


def _present_candidate_dates(state: WorkflowState, event_entry: dict) -> GroupResult:
    """[Trigger] Provide five deterministic candidate dates to the client."""

    requirements = event_entry.get("requirements") or {}
    preferred_room = requirements.get("preferred_room") or "Not specified"
    vague_month, vague_weekday, vague_time = _resolve_vague_components(state, event_entry)
    thread_id = _thread_id(state)

    if vague_month and vague_weekday:
        proposal = _build_vague_proposal(
            state,
            event_entry,
            preferred_room,
            vague_month,
            vague_weekday,
            vague_time,
            thread_id,
        )
    else:
        proposal = _build_generic_proposal(
            state,
            event_entry,
            preferred_room,
            thread_id,
        )

    body_with_footer = append_footer(
        "\n".join(proposal.body_lines),
        step=2,
        next_step="Confirm date",
        thread_state="Awaiting Client",
    )

    draft_message = {
        "body": body_with_footer,
        "step": 2,
        "next_step": "Confirm date",
        "thread_state": "Awaiting Client",
        "topic": proposal.topic,
        "candidate_dates": proposal.candidate_dates,
        "table_blocks": proposal.table_blocks,
        "actions": proposal.actions,
    }
    state.add_draft_message(draft_message)

    update_event_metadata(
        event_entry,
        thread_state="Awaiting Client",
        current_step=2,
        candidate_dates=proposal.candidate_dates,
    )
    _trace_candidate_gate(thread_id, proposal.candidate_dates)
    trace_state(
        thread_id,
        "Step2_Date",
        {
            "candidate_dates": proposal.candidate_dates,
            "vague_month": event_entry.get("vague_month"),
            "vague_weekday": event_entry.get("vague_weekday"),
        },
    )
    state.set_thread_state("Awaiting Client")
    state.extras["persist"] = True

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "candidate_dates": proposal.candidate_dates,
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
    }
    return GroupResult(action="date_options_proposed", payload=payload, halt=True)


def _resolve_vague_components(
    state: WorkflowState,
    event_entry: dict,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Collect vague date hints from the latest turn or persisted metadata."""

    user_info = state.user_info or {}
    month_token = user_info.get("vague_month") or event_entry.get("vague_month")
    weekday_token = user_info.get("vague_weekday") or event_entry.get("vague_weekday")
    time_token = user_info.get("vague_time_of_day") or event_entry.get("vague_time_of_day")

    def _normalize(value: Optional[str]) -> Optional[str]:
        if not value or not isinstance(value, str):
            return None
        stripped = value.strip()
        return stripped or None

    return _normalize(month_token), _normalize(weekday_token), _normalize(time_token)


def _build_vague_proposal(
    state: WorkflowState,
    event_entry: dict,
    preferred_room: str,
    vague_month: str,
    vague_weekday: str,
    vague_time: Optional[str],
    thread_id: str,
) -> DateProposal:
    """Enumerate Saturdays within the requested month and expose availability."""

    month_number = month_name_to_number(vague_month)
    weekday_number = weekday_name_to_number(vague_weekday)
    if not month_number or weekday_number is None:
        return _build_generic_proposal(state, event_entry, preferred_room)

    today = dt.datetime.now(TZ_ZURICH).date()
    blocked = blackout_days()
    descriptor_month = vague_month.capitalize()
    descriptor_weekday = vague_weekday.capitalize()
    time_label = _format_time_label(vague_time)

    collected: List[dict] = []
    for year in (today.year, today.year + 1):
        occurrences = [
            candidate
            for candidate in enumerate_month_weekday(year, month_number, weekday_number)
            if candidate >= today
        ]
        if not occurrences:
            continue
        for candidate in occurrences:
            ddmmyyyy = candidate.strftime("%d.%m.%Y")
            status = room_status_on_date(state.db, ddmmyyyy, preferred_room)
            blocked_flag = candidate in blocked
            available = status == "Available" and not blocked_flag
            collected.append(
                {
                    "date": candidate,
                    "ddmmyyyy": ddmmyyyy,
                    "status": status or "Unavailable",
                    "available": available,
                    "blocked": blocked_flag,
                }
            )
        if collected:
            break

    if not collected:
        return _build_generic_proposal(state, event_entry, preferred_room)

    available_rows = [entry for entry in collected if entry["available"]]
    primary_rows = available_rows if available_rows else collected
    primary_rows = primary_rows[:5]

    body_lines = [
        f"You mentioned a {descriptor_weekday} in {descriptor_month}.",
    ]
    if time_label:
        body_lines[0] = (
            f"You mentioned a {descriptor_weekday} {time_label.lower()} in {descriptor_month}."
        )
    if available_rows:
        body_lines.append("Here are the upcoming options that are still free:")
    else:
        body_lines.append(
            f"The {descriptor_weekday}s in {descriptor_month} are booked, "
            "but here is the list in case one is flexible for you."
        )

    table_rows = [
        _build_table_row(
            row["date"],
            row["status"],
            row["available"],
            time_label,
            "Blackout window" if row["blocked"] else None,
        )
        for row in primary_rows
    ]

    actions = [
        _build_select_date_action(row["date"], row["ddmmyyyy"], time_label)
        for row in available_rows[:5]
    ]
    candidate_dates = [row["ddmmyyyy"] for row in available_rows[:5]]

    # Offer next available dates outside the month when no Saturday is possible.
    table_blocks = [
        {
            "type": "dates",
            "label": f"{descriptor_weekday}s in {descriptor_month}",
            "rows": table_rows,
        }
    ]

    if not available_rows:
        fallback_dd = suggest_dates(
            state.db,
            preferred_room=preferred_room,
            start_from_iso=state.message.ts,
            days_ahead=90,
            max_results=5,
        )
        trace_db_read(thread_id, "db.dates.next5", {"preferred_room": preferred_room, "count": len(fallback_dd)})
        fallback_rows: List[dict] = []
        for value in fallback_dd:
            parsed = _safe_parse_ddmmyyyy(value)
            if not parsed:
                continue
            fallback_rows.append(
                _build_table_row(
                    parsed,
                    "Available",
                    True,
                    time_label,
                    "Nearest availability",
                )
            )
            actions.append(_build_select_date_action(parsed, value, time_label))
            candidate_dates.append(value)
        if fallback_rows:
            body_lines.append("I’ve also listed the closest open dates we can host you on.")
            table_blocks.append(
                {
                    "type": "dates",
                    "label": "Next available dates",
                    "rows": fallback_rows[:5],
                }
            )

    return DateProposal(
        body_lines=body_lines,
        candidate_dates=candidate_dates,
        table_blocks=table_blocks,
        actions=actions,
        topic="vague_date_candidates",
    )


def _build_generic_proposal(
    state: WorkflowState,
    event_entry: dict,
    preferred_room: str,
    thread_id: str,
) -> DateProposal:
    """Fallback path when we cannot rely on vague-month signals."""

    candidate_dates = suggest_dates(
        state.db,
        preferred_room=preferred_room,
        start_from_iso=state.message.ts,
        days_ahead=45,
        max_results=5,
    )
    trace_db_read(thread_id, "db.dates.next5", {"preferred_room": preferred_room, "count": len(candidate_dates)})

    body_lines: List[str] = ["Here are the next dates we can offer you:"]
    table_rows: List[dict] = []
    actions: List[dict] = []
    normalized_candidates: List[str] = []

    for value in candidate_dates:
        parsed = _safe_parse_ddmmyyyy(value)
        if not parsed:
            continue
        normalized_candidates.append(value)
        table_rows.append(
            _build_table_row(
                parsed,
                "Available",
                True,
                None,
            )
        )
        actions.append(_build_select_date_action(parsed, value, None))

    if normalized_candidates:
        body_lines.append("Let me know which one works best and I’ll lock it in.")
    else:
        body_lines.append(
            "Nothing is open in the next 45 days. Share a preferred timeframe and I’ll search wider."
        )

    table_blocks = []
    if table_rows:
        table_blocks.append(
            {
                "type": "dates",
                "label": "Upcoming availability",
                "rows": table_rows,
            }
        )

    return DateProposal(
        body_lines=body_lines,
        candidate_dates=normalized_candidates,
        table_blocks=table_blocks,
        actions=actions,
    )


def _build_table_row(
    date_value: dt.date,
    status: str,
    available: bool,
    time_label: Optional[str],
    note: Optional[str] = None,
) -> dict:
    row = {
        "iso_date": date_value.isoformat(),
        "display": _format_display(date_value),
        "status": "Available" if available else (status or "Unavailable"),
    }
    if time_label:
        row["time_of_day"] = time_label
    if note:
        row["note"] = note
    return row


def _build_select_date_action(
    date_value: dt.date,
    ddmmyyyy: str,
    time_label: Optional[str],
) -> dict:
    label = _format_display(date_value)
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


def _format_display(date_value: dt.date) -> str:
    return date_value.strftime("%a %d %b %Y")


def _safe_parse_ddmmyyyy(value: str) -> Optional[dt.date]:
    try:
        return dt.datetime.strptime(value, "%d.%m.%Y").date()
    except ValueError:
        return None


def _trace_candidate_gate(thread_id: str, candidates: List[str]) -> None:
    count = len(candidates)
    if count == 0:
        label = "feasible=0"
    elif count == 1:
        label = "feasible=1"
    else:
        label = "feasible=many"
    trace_gate(thread_id, "Step2_Date", label, True, {"count": count})


def _thread_id(state: WorkflowState) -> str:
    if state.thread_id:
        return str(state.thread_id)
    if state.client_id:
        return str(state.client_id)
    msg_id = state.message.msg_id if state.message else None
    if msg_id:
        return str(msg_id)
    return "unknown-thread"


def _resolve_confirmed_date(state: WorkflowState) -> str | None:
    """[Trigger] Determine the confirmed date from user input."""

    user_event_date = state.user_info.get("event_date")
    if user_event_date and is_valid_ddmmyyyy(user_event_date):
        return user_event_date

    iso_date = state.user_info.get("date")
    if iso_date:
        canonical = format_iso_date_to_ddmmyyyy(iso_date)
        if canonical:
            return canonical
    event_entry = state.event_entry or {}
    stored_date = event_entry.get("chosen_date")
    if stored_date and is_valid_ddmmyyyy(stored_date):
        return stored_date
    return None


def _finalize_confirmation(state: WorkflowState, event_entry: dict, confirmed_date: str) -> GroupResult:
    """[Trigger] Persist the confirmed date and route to the next step."""

    thread_id = _thread_id(state)
    state.event_id = event_entry.get("event_id")
    tag_message(event_entry, state.message.msg_id)

    event_entry.setdefault("event_data", {})["Event Date"] = confirmed_date
    update_event_metadata(
        event_entry,
        chosen_date=confirmed_date,
        date_confirmed=True,
        thread_state="Waiting on HIL",
    )
    trace_db_write(thread_id, "db.events.update_date", {"event_id": state.event_id, "date": confirmed_date})

    caller_step = event_entry.get("caller_step")
    next_step = caller_step if caller_step else 3
    append_audit_entry(event_entry, 2, next_step, "date_confirmed")
    update_event_metadata(event_entry, current_step=next_step, caller_step=None)

    reply = compose_date_confirmation_reply(confirmed_date, _preferred_room(event_entry))
    draft_message = {
        "body_markdown": reply,
        "step": 2,
        "next_step": "Room availability review",
        "thread_state": "Waiting on HIL",
        "topic": "date_confirmation",
        "date": confirmed_date,
    }
    state.add_draft_message(draft_message)

    if state.client and state.event_id:
        link_event_to_client(state.client, state.event_id)

    state.set_thread_state("Waiting on HIL")
    state.current_step = next_step
    state.caller_step = None
    state.extras["persist"] = True

    trace_state(
        thread_id,
        "Step2_Date",
        {
            "confirmed_date": confirmed_date,
            "next_step": next_step,
            "caller_step": caller_step,
        },
    )

    payload = {
        "client_id": state.client_id,
        "event_id": state.event_id,
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "event_date": confirmed_date,
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "next_step": next_step,
        "context": state.context_snapshot,
        "persisted": True,
    }
    return GroupResult(action="date_confirmed", payload=payload)


def _preferred_room(event_entry: dict) -> str | None:
    """[Trigger] Helper to extract preferred room from requirements."""

    requirements = event_entry.get("requirements") or {}
    return requirements.get("preferred_room")
