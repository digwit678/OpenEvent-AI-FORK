from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from backend.workflows.common.catalog import list_free_dates
from backend.workflows.common.prompts import append_footer
from backend.workflows.common.sorting import rank_rooms
from backend.workflows.common.timeutils import format_iso_date_to_ddmmyyyy, parse_ddmmyyyy
from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflows.io.dates import next5
from backend.workflows.nlu import detect_general_room_query
from backend.debug.hooks import (
    set_subloop,
    trace_db_read,
    trace_db_write,
    trace_entity,
    trace_marker,
    trace_gate,
    trace_state,
    trace_step,
)
from backend.workflows.io.database import (
    append_audit_entry,
    link_event_to_client,
    load_rooms,
    record_room_search_start,
    tag_message,
    update_event_date,
    update_event_metadata,
)
from backend.utils.profiler import profile_step

from ..condition.decide import is_valid_ddmmyyyy
from backend.workflows.groups.room_availability.condition.decide import room_status_on_date
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


def _search_range_availability(
    state: WorkflowState,
    thread_id: Optional[str],
    constraints: Dict[str, Any],
    participants: Optional[int],
    preferences: Dict[str, Any],
    preferred_room: Optional[str],
) -> List[Dict[str, Any]]:
    iso_dates = _candidate_dates_for_constraints(state, constraints)
    if not iso_dates:
        return []

    rooms = load_rooms()
    results: List[Dict[str, Any]] = []
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
                    "date_label": _format_range_label(iso_date),
                    "room": entry.room,
                    "status": entry.status,
                    "hint": _format_hint(entry.hint),
                }
            )
        if len(results) >= 5:
            break

    if thread_id:
        trace_db_read(
            thread_id,
            "Step2_Date",
            "db.rooms.search_range",
            {
                "constraints": {
                    "month": constraints.get("vague_month") or (state.user_info or {}).get("vague_month"),
                    "weekday": constraints.get("weekday"),
                    "time_of_day": constraints.get("time_of_day"),
                    "pax": participants,
                },
                "result_count": len(results),
                "sample": results[:3],
            },
        )

    return results[:5]


def _candidate_dates_for_constraints(state: WorkflowState, constraints: Dict[str, Any], limit: int = 5) -> List[str]:
    rules: Dict[str, Any] = {"timezone": "Europe/Zurich"}
    event_entry = state.event_entry or {}
    month = constraints.get("vague_month") or state.user_info.get("vague_month") or event_entry.get("vague_month")
    if month:
        rules["month"] = month
    weekday = constraints.get("weekday") or state.user_info.get("vague_weekday") or event_entry.get("vague_weekday")
    if isinstance(weekday, list) and weekday:
        rules["weekday"] = weekday[0]
    elif isinstance(weekday, str):
        rules["weekday"] = weekday
    dates = next5(state.message.ts if state.message else None, rules)
    return [value.strftime("%Y-%m-%d") for value in dates[:limit]]


def _describe_constraints(constraints: Dict[str, Any], state: WorkflowState) -> str:
    month = constraints.get("vague_month") or state.user_info.get("vague_month")
    weekday = constraints.get("weekday") or state.user_info.get("vague_weekday")
    time_of_day = constraints.get("time_of_day") or state.user_info.get("vague_time_of_day")

    parts: List[str] = []
    if weekday:
        if isinstance(weekday, list):
            formatted = ", ".join(word.capitalize() for word in weekday)
        else:
            formatted = str(weekday).capitalize()
        parts.append(formatted)
    if month:
        parts.append(f"in {str(month).capitalize()}")

    descriptor = " ".join(parts) if parts else "for your requested window"
    if time_of_day:
        descriptor += f" ({str(time_of_day).lower()})"
    return descriptor


def _format_range_label(iso_date: str) -> str:
    try:
        base_date = dt.date.fromisoformat(iso_date)
    except ValueError:
        return iso_date
    return base_date.strftime("%a %d %b %Y")


def _format_hint(text: Optional[str]) -> str:
    value = (text or "").strip()
    if not value:
        return "Catering available"
    return value[0].upper() + value[1:]


def _format_room_availability(entries: List[Dict[str, Any]]) -> List[str]:
    grouped: Dict[str, List[Tuple[str, str]]] = {}
    for entry in entries:
        room = str(entry.get("room") or "Room").strip() or "Room"
        date_label = entry.get("date_label") or _format_range_label(entry.get("iso_date") or "")
        status = entry.get("status") or "Available"
        bucket = grouped.setdefault(room, [])
        bucket.append((date_label, status))

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
        highlights = ", ".join(wish_products[:2])
        lines.append(f"- Highlights: {highlights}. We'll share full details once the date is locked in.")
    else:
        lines.append("- Seasonal dinner menus and wine pairings available; happy to tailor once you confirm.")
    return lines


def _user_requested_products(state: WorkflowState, classification: Dict[str, Any]) -> bool:
    message_text = (_message_text(state) or "").lower()
    keywords = ("menu", "cater", "product")
    if any(keyword in message_text for keyword in keywords):
        return True
    parsed = classification.get("parsed") or {}
    if isinstance(parsed, dict):
        if parsed.get("products") or parsed.get("catering"):
            return True
    return False


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

    iso_candidate = state.user_info.get("date")
    iso_date = iso_candidate if isinstance(iso_candidate, str) else None
    if not iso_date:
        parsed = parse_ddmmyyyy(confirmed_date)
        if parsed:
            iso_date = parsed.strftime("%Y-%m-%d")

    try:
        if state.event_id and iso_date:
            event_entry = update_event_date(state.db, state.event_id, iso_date)
            state.event_entry = event_entry
        else:
            event_entry.setdefault("event_data", {})["Event Date"] = confirmed_date
            update_event_metadata(
                event_entry,
                chosen_date=confirmed_date,
                date_confirmed=True,
            )
    except ValueError:
        event_entry.setdefault("event_data", {})["Event Date"] = confirmed_date
        update_event_metadata(
            event_entry,
            chosen_date=confirmed_date,
            date_confirmed=True,
        )

    trace_db_write(
        thread_id,
        "Step2_Date",
        "db.events.update_date",
        {"event_id": state.event_id, "date_iso": iso_date or "unknown"},
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

    pax_label, pax_count = _participants_metadata(event_entry)
    if state.event_id and iso_date:
        try:
            record_room_search_start(
                state.db,
                state.event_id,
                date_iso=iso_date,
                participants=pax_count,
            )
            trace_db_write(
                thread_id,
                "Step2_Date",
                "db.rooms.search_start",
                {"event_id": state.event_id, "date_iso": iso_date, "participants": pax_count},
            )
        except ValueError:
            pass

    append_audit_entry(event_entry, 2, 3, "date_confirmed")
    update_event_metadata(
        event_entry,
        current_step=3,
        caller_step=None,
        thread_state="Checking",
    )

    acknowledgement = compose_date_confirmation_reply(confirmed_date, pax_label)
    acknowledgement_with_footer = append_footer(
        acknowledgement,
        step=3,
        next_step="Availability result",
        thread_state="Checking",
    )
    state.add_draft_message(
        {
            "body": acknowledgement_with_footer,
            "step": 3,
            "next_step": "Availability result",
            "thread_state": "Checking",
            "topic": "date_confirmation_ack",
            "requires_approval": False,
            "date": confirmed_date,
        }
    )

    if state.client and state.event_id:
        link_event_to_client(state.client, state.event_id)

    trace_marker(
        thread_id,
        "ROUTE Step3_Room",
        data={"from": 2, "to": 3, "reason": "date_confirmed"},
        owner_step="Step2_Date",
        granularity="logic",
    )

    state.set_thread_state("Checking")
    state.current_step = 3
    state.caller_step = None
    state.event_entry = event_entry
    state.extras["persist"] = True

    trace_state(
        thread_id,
        "Step2_Date",
        {
            "confirmed_date": confirmed_date,
            "next_step": 3,
            "thread_state": "Checking",
        },
    )

    payload = {
        "client_id": state.client_id,
        "event_id": state.event_id,
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "event_date": confirmed_date,
        "assistant_message": acknowledgement_with_footer,
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "next_step": 3,
        "context": state.context_snapshot,
        "persisted": True,
    }
    return GroupResult(action="date_confirmed", payload=payload)


def _extract_participant_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if value <= 0:
            return None
        return int(value)
    if isinstance(value, str):
        match = re.search(r"\d{1,4}", value)
        if match:
            try:
                number = int(match.group(0))
                return number if number > 0 else None
            except ValueError:
                return None
    return None


def _participants_metadata(event_entry: dict) -> Tuple[str, Optional[int]]:
    """Return a human-friendly participant label and numeric count when known."""

    requirements = event_entry.get("requirements") or {}
    event_data = event_entry.get("event_data") or {}

    candidates = [
        requirements.get("number_of_participants"),
        event_data.get("Number of Participants"),
    ]

    for candidate in candidates:
        number = _extract_participant_int(candidate)
        if number:
            label = f"{number} guests" if number != 1 else "1 guest"
            return (label, number)

    for candidate in candidates:
        if isinstance(candidate, str):
            text = candidate.strip()
            if text and text.lower() not in {"not specified", "none"}:
                return (text, None)

    return ("your group", None)


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
    subloop_label = "general_q_a"
    state.extras["subloop"] = subloop_label
    if thread_id:
        set_subloop(thread_id, subloop_label)
    candidate_dates = list_free_dates(
        count=5,
        db=state.db,
        preferred_room=preferred_room,
    )

    participants = _extract_participants_from_state(state)
    preferences = event_entry.get("preferences") or state.user_info.get("preferences") or {}
    constraints = classification.get("constraints") or {}

    range_results: List[Dict[str, Any]] = []
    if classification.get("is_general") and _is_hybrid_availability_request(classification, state):
        range_results = _search_range_availability(
            state,
            thread_id,
            constraints,
            participants,
            preferences,
            preferred_room,
        )

    if thread_id and not range_results:
        trace_db_read(
            thread_id,
            "Step2_Date",
            "db.dates.general_qna",
            {
                "count": len(candidate_dates),
                "preferred_room": preferred_room,
                "constraints": constraints,
            },
        )

    descriptor: Optional[str] = None
    products_requested = _user_requested_products(state, classification)
    if range_results:
        descriptor = _describe_constraints(constraints, state)
        availability_lines = _format_room_availability(range_results)
        info_lines = []
        if descriptor:
            info_lines.append(f"I checked availability {descriptor}:")
        info_lines.extend(availability_lines)
        info_lines.append("")
        if products_requested:
            info_lines.extend(_compact_products_summary(preferences))
            info_lines.append("")
        info_lines.append("Pick a date below to confirm and I'll lock it in immediately.")
        body = "\n".join(info_lines)
    else:
        info_lines = []
        if candidate_dates:
            info_lines.append("Room availability snapshot:")
            for value in candidate_dates:
                info_lines.append(f"- {preferred_room}: {value}")
        else:
            info_lines.append("- Share a preferred month or weekday and I can re-check the calendar right away.")
        info_lines.append("")
        if products_requested:
            info_lines.extend(_compact_products_summary(preferences))
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
    actions: List[Dict[str, Any]] = []
    for candidate in candidate_dates:
        parsed = parse_ddmmyyyy(candidate)
        if parsed:
            actions.append(_build_select_date_action(parsed, candidate, None))
    if actions:
        draft_message["actions"] = actions
    if range_results:
        draft_message["range_results"] = range_results
        if descriptor:
            draft_message["range_descriptor"] = descriptor
    state.add_draft_message(draft_message)

    update_event_metadata(
        event_entry,
        thread_state="Awaiting Client",
        current_step=2,
        candidate_dates=candidate_dates,
    )

    state.set_thread_state("Awaiting Client")
    if thread_id:
        trace_state(
            thread_id,
            "Step2_Date",
            {
                "thread_state": state.thread_state,
                "candidate_dates": candidate_dates,
                "subloop": subloop_label,
            },
        )
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
    if range_results:
        payload["range_results"] = range_results
        if descriptor:
            payload["range_descriptor"] = descriptor
    return GroupResult(action="general_rooms_qna", payload=payload, halt=True)
