"""
Step 3 (Room Availability) - Constants and configuration values.

This module contains constants used throughout the Step 3 room availability workflow.
"""

from __future__ import annotations

# Room outcome status strings
ROOM_OUTCOME_UNAVAILABLE = "Unavailable"
ROOM_OUTCOME_AVAILABLE = "Available"
ROOM_OUTCOME_OPTION = "Option"
ROOM_OUTCOME_CAPACITY_EXCEEDED = "CapacityExceeded"

# Room size ordering for ranking (smaller number = smaller room)
ROOM_SIZE_ORDER = {
    "Room A": 1,
    "Room B": 2,
    "Room C": 3,
    "Punkt.Null": 4,
}

# Number of room proposals before requiring HIL approval
# TODO(openevent-team): make this configurable per venue
ROOM_PROPOSAL_HIL_THRESHOLD = 3
