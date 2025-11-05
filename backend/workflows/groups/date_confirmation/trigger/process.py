from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from backend.workflows.common.catalog import list_free_dates
from backend.workflows.common.prompts import append_footer
from backend.workflows.common.timeutils import format_iso_date_to_ddmmyyyy
from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflows.io.dates import next5
from backend.workflows.nlu import detect_general_room_query
from backend.debug.hooks import (
    trace_db_read,
    trace_db_write,
    trace_entity,
    trace_marker,
    trace_gate,
    trace_state,
    trace_step,
)
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

    message_text = _message_text(state)
    classification = detect_general_room_query(message_text, state)
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
            granularity="logic",
        )

    if classification["is_general"] and not bool(event_entry.get("date_confirmed")):
        return _present_general_room_qna(state, event_entry, classification, thread_id)

    chosen_date = event_entry.get("chosen_date")
    if not chosen_date:
        return _present_candidate_dates(state, event_entry)

    confirmed_date = _resolve_confirmed_date(state)
    if not confirmed_date:
        return _present_candidate_dates(state, event_entry)

    return _finalize_confirmation(state, event_entry, confirmed_date)


def _present_candidate_dates(state: WorkflowState, event_entry: dict) -> GroupResult:
    """[Trigger] Provide five deterministic candidate dates to the client."""

    vague_month, vague_weekday, vague_time = _resolve_vague_components(state, event_entry)
    thread_id = _thread_id(state)

    proposal = _build_date_proposal(
        state,
        vague_month=vague_month,
        vague_weekday=vague_weekday,
        vague_time=vague_time,
        thread_id=thread_id,
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


def _build_date_proposal(
    state: WorkflowState,
    vague_month: Optional[str],
    vague_weekday: Optional[str],
    vague_time: Optional[str],
    thread_id: str,
) -> DateProposal:
    """Produce a deterministic set of candidate dates and the accompanying draft content."""

    base_ts = state.message.ts if state.message else None
    time_label = _format_time_label(vague_time)
    timezone_name = "Europe/Zurich"
    rules: dict = {"timezone": timezone_name}

    if vague_weekday:
        rules["weekday"] = vague_weekday
    if vague_month:
        rules["month"] = vague_month

    primary_dates = next5(base_ts, rules)
    fallback_dates: List[dt.date] = []
    if len(primary_dates) < 5:
        fallback_rules = {"timezone": timezone_name}
        fallback_dates = [candidate for candidate in next5(base_ts, fallback_rules) if candidate not in primary_dates]

    all_dates = (primary_dates + fallback_dates)[:5]
    trace_db_read(
        thread_id,
        "Step2_Date",
        "db.dates.next5",
        {"dates": [value.isoformat() for value in all_dates]},
    )

    candidate_dates: List[str] = []
    table_rows: List[dict] = []
    actions: List[dict] = []
    for date_value in all_dates:
        ddmmyyyy = date_value.strftime("%d.%m.%Y")
        candidate_dates.append(ddmmyyyy)
        table_rows.append(_build_table_row(date_value, "Available", True, time_label))
        actions.append(_build_select_date_action(date_value, ddmmyyyy, time_label))

    descriptor_month = (vague_month or "").strip().capitalize()
    descriptor_weekday = (vague_weekday or "").strip().capitalize()
    topic = "generic_date_candidates"

    if vague_month and vague_weekday:
        first_line = f"You mentioned a {descriptor_weekday}"
        if time_label:
            first_line += f" {time_label.lower()}"
        first_line += f" in {descriptor_month}."
        body_lines = [
            first_line,
            "Here are the upcoming options that are still free:",
        ]
        topic = "vague_date_candidates"
        table_label = f"{descriptor_weekday}s in {descriptor_month}"
    else:
        body_lines = [
            "Here are the next dates we can offer you:",
        ]
        table_label = "Upcoming availability"

    body_lines.append("If none of these dates work, let me know another date and I'll recheck availability.")

    table_blocks = [
        {
            "type": "dates",
            "label": table_label,
            "rows": table_rows,
        }
    ]

    return DateProposal(
        body_lines=body_lines,
        candidate_dates=candidate_dates,
        table_blocks=table_blocks,
        actions=actions,
        topic=topic,
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
    trace_db_write(
        thread_id,
        "Step2_Date",
        "db.events.update_date",
        {"event_id": state.event_id, "date": confirmed_date},
    )
    trace_entity(
        thread_id,
        "Step2_Date",
        "date",
        "confirmation_step",
        True,
        {"value": confirmed_date},
        status_override="confirmed",
    )

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


def _message_text(state: WorkflowState) -> str:
    message = state.message
    if not message:
        return ""
    subject = message.subject or ""
    body = message.body or ""
    if subject and body:
        return f"{subject}\n{body}"
    return subject or body


def _present_general_room_qna(
    state: WorkflowState,
    event_entry: dict,
    classification: Dict[str, Any],
    thread_id: Optional[str],
) -> GroupResult:
    requirements = event_entry.get("requirements") or {}
    preferred_room = requirements.get("preferred_room") or "Room A"
    candidate_dates = list_free_dates(
        count=5,
        db=state.db,
        preferred_room=preferred_room,
    )

    if thread_id:
        trace_db_read(
            thread_id,
            "Step2_Date",
            "db.dates.general_qna",
            {
                "count": len(candidate_dates),
                "preferred_room": preferred_room,
                "constraints": classification.get("constraints"),
            },
        )

    info_lines = [
        "ROOM AVAILABILITY SNAPSHOT:",
    ]
    if candidate_dates:
        for value in candidate_dates:
            info_lines.append(f"- {value} · {preferred_room} currently shows as available.")
    else:
        info_lines.append("- Share a preferred month or weekday and I'll recheck availability immediately.")
    info_lines.append("")
    info_lines.append("NEXT STEP:")
    info_lines.append("- Tell me which date works best and I'll lock the room right away.")
    body = "\n".join(info_lines)
    body_with_footer = append_footer(
        body,
        step=2,
        next_step="Confirm date",
        thread_state="Awaiting Client",
    )

    draft_message = {
        "body": body_with_footer,
        "step": 2,
        "next_step": "Confirm date",
        "thread_state": "Awaiting Client",
        "topic": "general_room_qna",
        "candidate_dates": candidate_dates,
        "actions": [],
    }
    state.add_draft_message(draft_message)

    update_event_metadata(
        event_entry,
        thread_state="Awaiting Client",
        current_step=2,
        candidate_dates=candidate_dates,
    )

    state.set_thread_state("Awaiting Client")
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
        "general_room_constraints": classification.get("constraints"),
    }
    return GroupResult(action="general_rooms_qna", payload=payload, halt=True)
