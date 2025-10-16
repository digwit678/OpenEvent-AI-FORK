from __future__ import annotations

from workflows.common.timeutils import format_ts_to_ddmmyyyy
from workflows.common.types import GroupResult, WorkflowState
from workflows.conditions.checks import is_valid_ddmmyyyy
from workflows.io.database import (
    create_event_entry,
    default_event_record,
    find_event_idx,
    link_event_to_client,
    tag_message,
    update_event_entry,
)


def process(state: WorkflowState) -> GroupResult:
    """[Trigger] Run Group B — date negotiation and confirmation."""

    event_date = state.user_info.get("event_date")
    if not is_valid_ddmmyyyy(event_date):
        payload = {
            "client_id": state.client_id,
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "reason": "invalid_event_date",
            "user_info": state.user_info,
            "context": state.context_snapshot,
        }
        return GroupResult(action="date_invalid", payload=payload, halt=True)

    msg_payload = state.message.to_payload()
    received_date = format_ts_to_ddmmyyyy(state.message.ts)
    enriched_info = dict(state.user_info)
    enriched_info["event_date"] = event_date
    event_data = default_event_record(enriched_info, msg_payload, received_date)
    idx = find_event_idx(state.db, msg_payload.get("from_email", ""), event_data["Event Date"])

    client = state.client
    if idx is None:
        event_id = create_event_entry(state.db, event_data)
        state.event_id = event_id
        state.event_entry = state.db["events"][-1]
        state.updated_fields = []
        if client:
            link_event_to_client(client, event_id)
        event_action = "created_event"
    else:
        state.event_entry = state.db["events"][idx]
        state.event_id = state.event_entry["event_id"]
        state.updated_fields = update_event_entry(state.db, idx, event_data)
        if client:
            link_event_to_client(client, state.event_id)
        event_action = "updated_event"

    tag_message(state.event_entry, msg_payload.get("msg_id"))
    state.extras["event_action"] = event_action
    state.extras["persist"] = True

    reply = compose_date_confirmation_reply(event_date, enriched_info.get("room"))
    payload = {
        "client_id": state.client_id,
        "event_id": state.event_id,
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "event_date": event_date,
        "reply": reply,
        "updated_fields": state.updated_fields,
        "context": state.context_snapshot,
        "persisted": True,
        "user_info": enriched_info,
        "event_action": event_action,
    }
    return GroupResult(action="date_confirmed", payload=payload)


def compose_date_confirmation_reply(event_date: str, preferred_room: str | None) -> str:
    """[LLM] Draft a short acknowledgement for the confirmed date."""

    if preferred_room and preferred_room != "Not specified":
        return (
            f"Thank you for confirming {event_date}. "
            f"We have noted {preferred_room} and will share availability updates shortly."
        )
    return (
        f"Thank you for confirming {event_date}. "
        "We will check room availability and follow up with the options."
    )
