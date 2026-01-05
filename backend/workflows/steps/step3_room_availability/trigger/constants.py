"""
Step 3 (Room Availability) - Constants and configuration values.

This module contains constants used throughout the Step 3 room availability workflow.
"""

from __future__ import annotations

from typing import Dict

# Room outcome status strings
ROOM_OUTCOME_UNAVAILABLE = "Unavailable"
ROOM_OUTCOME_AVAILABLE = "Available"
ROOM_OUTCOME_OPTION = "Option"
ROOM_OUTCOME_CAPACITY_EXCEEDED = "CapacityExceeded"


def get_room_size_order() -> Dict[str, int]:
    """Get room size ordering from JSON config.

    Room order is based on position in rooms.json (first = smallest).
    Returns dict mapping room name to order (1 = smallest).
    """
    from backend.workflows.io.database import load_rooms

    rooms = load_rooms()
    # Order by position in config (first room = 1, etc.)
    return {name: idx + 1 for idx, name in enumerate(rooms)}


# Number of room proposals before requiring HIL approval
# TODO(openevent-team): make this configurable per venue
ROOM_PROPOSAL_HIL_THRESHOLD = 3
