from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from workflows.common.types import GroupResult, WorkflowState


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
    """[OpenEvent Database] Evaluate each room for the requested event date."""

    rooms = load_rooms()
    statuses: List[Dict[str, str]] = []
    for room_name in rooms:
        status = room_status_on_date(db, target_date, room_name)
        statuses.append({room_name: status})
    return statuses


def room_status_on_date(db: Dict[str, Any], date_ddmmyyyy: str | None, room_name: str) -> str:
    """[Condition] Derive the availability for a specific room on a given date."""

    if not date_ddmmyyyy:
        return "Unavailable"
    room_lc = room_name.lower()
    status_found = "Available"
    for event in db.get("events", []):
        data = event.get("event_data", {})
        if data.get("Event Date") != date_ddmmyyyy:
            continue
        stored_room = data.get("Preferred Room")
        if not stored_room or stored_room.lower() != room_lc:
            continue
        normalized = (data.get("Status") or "").lower()
        if normalized == "confirmed":
            return "Confirmed"
        if normalized in {"option", "lead"}:
            status_found = "Option"
    return status_found


def load_rooms() -> List[str]:
    """[OpenEvent Database] Load room names from the canonical configuration file."""

    rooms_path = Path(__file__).resolve().parents[2] / "rooms.json"
    if not rooms_path.exists():
        return ["Punkt.Null", "Room A", "Room B", "Room C"]
    with rooms_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    rooms = payload.get("rooms") or []
    return [room.get("name") for room in rooms if room.get("name")]


def summarize_room_statuses(statuses: List[Dict[str, str]]) -> str:
    """[LLM] Produce a concise textual summary from room status data."""

    fragments = []
    for entry in statuses:
        for room, status in entry.items():
            fragments.append(f"{room}: {status}")
    joined = "; ".join(fragments) if fragments else "No rooms configured."
    return f"Room availability summary — {joined}."
