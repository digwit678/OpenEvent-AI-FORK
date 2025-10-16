from __future__ import annotations

from typing import Any, Dict, List

from workflows.common.types import GroupResult, WorkflowState
from workflows.io.database import load_rooms

from .condition import room_status_on_date
from .llm import summarize_room_statuses

__workflow_role__ = "Trigger"


def process(state: WorkflowState) -> GroupResult:
    """[Trigger] Execute Group C — room availability assessment."""

    event_date = state.user_info.get("event_date")
    room_statuses = evaluate_room_statuses(state.db, event_date)
    summary = summarize_room_statuses(room_statuses)

    payload = {
        "client_id": state.client_id,
        "event_id": state.event_id,
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "rooms": room_statuses,
        "summary": summary,
        "user_info": state.user_info,
        "context": state.context_snapshot,
        "event_action": state.extras.get("event_action"),
        "updated_fields": state.updated_fields,
        "persisted": True,
    }
    return GroupResult(action="room_avail_result", payload=payload, halt=True)


def evaluate_room_statuses(db: Dict[str, Any], target_date: str | None) -> List[Dict[str, str]]:
    """[Trigger] Evaluate each configured room for the requested event date."""

    rooms = load_rooms()
    statuses: List[Dict[str, str]] = []
    for room_name in rooms:
        status = room_status_on_date(db, target_date, room_name)
        statuses.append({room_name: status})
    return statuses
