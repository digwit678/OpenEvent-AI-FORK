from __future__ import annotations

from typing import List

from backend.workflows.common.timeutils import format_iso_date_to_ddmmyyyy
from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflows.groups.intake.condition.checks import suggest_dates
from backend.workflows.io.database import append_audit_entry, link_event_to_client, tag_message, update_event_metadata
from backend.utils.profiler import profile_step

from ..condition.decide import is_valid_ddmmyyyy
from ..llm.analysis import compose_date_confirmation_reply

__workflow_role__ = "trigger"


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
    candidate_dates: List[str] = suggest_dates(
        state.db,
        preferred_room=preferred_room,
        start_from_iso=state.message.ts,
        days_ahead=45,
        max_results=5,
    )
    if not candidate_dates:
        candidate_dates = []

    options_text = "\n".join(f"- {value}" for value in candidate_dates) or "• No suitable slots in the next 45 days."
    prompt = (
        "Here are the next available dates at The Atelier:\n"
        f"{options_text}\n"
        "Please pick one that works for you, or share another date and I'll check it immediately."
    )

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
    }
    return GroupResult(action="date_options_proposed", payload=payload, halt=True)


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

    state.event_id = event_entry.get("event_id")
    tag_message(event_entry, state.message.msg_id)

    event_entry.setdefault("event_data", {})["Event Date"] = confirmed_date
    update_event_metadata(
        event_entry,
        chosen_date=confirmed_date,
        date_confirmed=True,
        thread_state="In Progress",
    )

    caller_step = event_entry.get("caller_step")
    next_step = caller_step if caller_step else 3
    append_audit_entry(event_entry, 2, next_step, "date_confirmed")
    update_event_metadata(event_entry, current_step=next_step, caller_step=None)

    reply = compose_date_confirmation_reply(confirmed_date, _preferred_room(event_entry))
    draft_message = {
        "body": reply,
        "step": 2,
        "topic": "date_confirmation",
        "date": confirmed_date,
    }
    state.add_draft_message(draft_message)

    if state.client and state.event_id:
        link_event_to_client(state.client, state.event_id)

    state.set_thread_state("In Progress")
    state.current_step = next_step
    state.caller_step = None
    state.extras["persist"] = True

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
