"""
Calendar event creation for workflow status transitions.
Placeholder implementation - to be replaced with actual calendar API integration.
"""

from __future__ import annotations

import json
import os
import logging
from datetime import datetime
from typing import Dict, Any

logger = logging.getLogger(__name__)


def create_calendar_event(event_entry: Dict[str, Any], event_type: str) -> Dict[str, Any]:
    """
    Create a calendar event for the booking.

    Args:
        event_entry: The event data from the database
        event_type: Type of calendar event (lead, option, confirmed)

    Returns:
        Calendar event data that would be sent to calendar API
    """
    event_id = event_entry.get("event_id")
    chosen_date = event_entry.get("chosen_date")
    room = event_entry.get("locked_room_id", "TBD")

    event_data = event_entry.get("event_data", {})
    client_name = event_data.get("Name", "Unknown Client")
    company = event_data.get("Company", "")

    participants = event_entry.get("number_of_participants", 0)
    if isinstance(participants, str):
        try:
            participants = int(participants)
        except Exception:
            participants = 0

    title_parts = [f"[{event_type.upper()}]", client_name]
    if company:
        title_parts.append(f"({company})")
    title_parts.append(f"- {room}")

    calendar_event = {
        "id": f"openevent-{event_id}",
        "title": " ".join(title_parts),
        "date": chosen_date,
        "room": room,
        "participants": participants,
        "status": event_type,
        "client": {
            "name": client_name,
            "company": company,
            "email": event_data.get("Email", ""),
            "phone": event_data.get("Phone", ""),
        },
        "description": f"Event booking for {client_name}\nParticipants: {participants}\nStatus: {event_type}\nRoom: {room}",
        "created_at": datetime.utcnow().isoformat(),
        "event_id": event_id,
    }

    logger.info("Created calendar event: %s for event %s", event_type, event_id)
    _log_calendar_event(calendar_event)

    return calendar_event


def update_calendar_event_status(event_id: str, old_status: str, new_status: str) -> bool:
    """Update existing calendar event when status changes."""
    try:
        update_data = {
            "event_id": f"openevent-{event_id}",
            "old_status": old_status,
            "new_status": new_status,
            "updated_at": datetime.utcnow().isoformat(),
        }

        logger.info("Updated calendar event: %s from %s to %s", event_id, old_status, new_status)
        _log_calendar_event(update_data, action="update")
        return True
    except Exception as exc:
        logger.error("Failed to update calendar event: %s", exc)
        return False


def _log_calendar_event(event_data: Dict[str, Any], action: str = "create") -> None:
    """Log calendar events to file for testing."""
    if os.getenv("VERCEL") == "1":
        log_dir = "/tmp/calendar_events"
    else:
        log_dir = "tmp-cache/calendar_events"
    os.makedirs(log_dir, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    event_id = event_data.get("event_id", "unknown")
    filename = f"{log_dir}/calendar_{action}_{event_id}_{timestamp}.json"

    try:
        with open(filename, "w", encoding="utf-8") as handle:
            json.dump(event_data, handle, indent=2)
        logger.debug("Logged calendar event to %s", filename)
    except Exception as exc:
        logger.error("Failed to log calendar event: %s", exc)
