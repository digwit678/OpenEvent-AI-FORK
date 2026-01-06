"""
Step 3 Room Evaluation and Rendering Functions.

Extracted from step3_handler.py as part of R4 refactoring (Dec 2025).

This module contains:
- evaluate_room_statuses: Evaluate room availability for a date
- render_rooms_response: Format room options for display
- _flatten_statuses: Convert status list to dict

Usage:
    from .evaluation import evaluate_room_statuses, render_rooms_response
"""

from __future__ import annotations

from typing import Any, Dict, List

from workflows.common.timeutils import format_iso_date_to_ddmmyyyy
from workflows.io.database import load_rooms

from ..condition.decide import room_status_on_date


def evaluate_room_statuses(db: Dict[str, Any], target_date: str | None) -> List[Dict[str, str]]:
    """[Trigger] Evaluate each configured room for the requested event date."""

    rooms = load_rooms()
    statuses: List[Dict[str, str]] = []
    for room_name in rooms:
        status = room_status_on_date(db, target_date, room_name)
        statuses.append({room_name: status})
    return statuses


def render_rooms_response(
    event_id: str,
    date_iso: str,
    pax: int,
    rooms: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Render a lightweight room summary for deterministic flow tests."""

    display_date = format_iso_date_to_ddmmyyyy(date_iso) or date_iso
    headers = [f"Room options for {display_date}"]
    lines: List[str] = []
    for room in rooms:
        matched = ", ".join(room.get("matched") or []) or "None"
        missing_items = room.get("missing") or []
        missing = ", ".join(missing_items) if missing_items else "None"
        capacity = room.get("capacity") or "—"
        name = room.get("name") or room.get("id") or "Room"
        lines.append(
            f"{name} — capacity {capacity} — matched: {matched} — missing: {missing}"
        )
    body = "\n".join(lines) if lines else "No rooms available."
    assistant_draft = {"headers": headers, "body": body}
    return {
        "action": "send_reply",
        "event_id": event_id,
        "rooms": rooms,
        "res": {
            "assistant_draft": assistant_draft,
            "assistant_draft_text": body,
        },
    }


def _flatten_statuses(statuses: List[Dict[str, str]]) -> Dict[str, str]:
    """[Trigger] Convert list of {room: status} mappings into a single dict."""

    result: Dict[str, str] = {}
    for entry in statuses:
        result.update(entry)
    return result


__all__ = [
    "evaluate_room_statuses",
    "render_rooms_response",
    "_flatten_statuses",
]
