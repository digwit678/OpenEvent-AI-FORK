"""Entity extraction helpers for Step 1.

Extracted from step1_handler.py as part of I1 refactoring (Dec 2025).
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def participants_from_event(event_entry: Optional[Dict[str, Any]]) -> Optional[int]:
    """Read participants count from event entry, checking multiple fallback locations.

    Returns:
        Participant count as int, or None if not found.
    """
    if not event_entry:
        return None
    requirements = event_entry.get("requirements") or {}
    candidates = [
        requirements.get("number_of_participants"),
        (event_entry.get("event_data") or {}).get("Number of Participants"),
        (event_entry.get("captured") or {}).get("participants"),
    ]
    for value in candidates:
        if value is None:
            continue
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            continue
    return None
