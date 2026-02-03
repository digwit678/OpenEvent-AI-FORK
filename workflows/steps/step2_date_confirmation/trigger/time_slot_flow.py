"""Event time slot selection flow.

Handles optional time slot booking when `require_selection` is enabled in config.
Mirrors site_visit_handler.py pattern for slot-based booking.

IMPORTANT: Uses LLM detection (time_slot_label) per the LLM-First Rule.
Never use keywords to override LLM semantic understanding.

Flow:
    1. Date confirmed but no specific time provided
    2. Check if time slot selection is required (config)
    3. Present Morning/Afternoon/Evening options
    4. Client selects slot (via LLM detection)
    5. Map slot to start/end times
    6. Proceed to Step 3

State:
    event_entry["event_time_slot_pending"] = {
        "date_iso": str,
        "date_display": str,
        "slots": list[str],  # ["Morning (09:00-12:00)", ...]
    }
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from detection.unified import UnifiedDetectionResult
from workflows.io.config_store import get_event_time_slots, is_event_time_slot_required

logger = logging.getLogger(__name__)


def is_time_slot_pending(event_entry: Dict[str, Any]) -> bool:
    """Check if time slot selection is pending for this event."""
    return event_entry.get("event_time_slot_pending") is not None


def should_prompt_time_slot(
    event_entry: Dict[str, Any],
    start_time: Optional[str],
    end_time: Optional[str],
) -> bool:
    """Check if time slot selection should be prompted.

    Time slot prompting is required when:
    1. Feature is enabled in config (require_selection=true)
    2. No specific start/end time was provided by client
    3. Not in a detour (caller_step would be set)

    Args:
        event_entry: Current event entry dict
        start_time: Extracted start time (HH:MM) or None
        end_time: Extracted end time (HH:MM) or None

    Returns:
        True if we should prompt for time slot selection
    """
    if not is_event_time_slot_required():
        return False

    # If client already provided specific times, skip slot selection
    if start_time and end_time:
        return False

    # Skip during detours (when returning from another step)
    if event_entry.get("caller_step"):
        logger.debug("[TIME_SLOT] Skipping prompt - in detour from step %s",
                    event_entry.get("caller_step"))
        return False

    return True


def parse_slot_from_detection(
    detection: Optional[UnifiedDetectionResult],
    slots_config: List[Dict[str, Any]],
) -> Optional[Tuple[str, str]]:
    """Parse time slot from LLM detection result (LLM-First Rule).

    Uses the `time_slot_label` field from unified detection, which the LLM
    extracts when it recognizes slot names ("morning", "afternoon") or
    ordinals ("first", "second").

    Args:
        detection: Result from run_unified_detection()
        slots_config: List of slot configs from get_event_time_slots()

    Returns:
        Tuple of (start_time, end_time) in HH:MM format, or None if not found
    """
    if not detection or not detection.time_slot_label:
        return None

    label = detection.time_slot_label.lower().strip()
    logger.debug("[TIME_SLOT] Parsing label from LLM: '%s'", label)

    # Match by slot label (case-insensitive)
    for slot in slots_config:
        slot_label = slot.get("label", "").lower()
        if slot_label == label:
            start_hour = slot.get("start", 9)
            end_hour = slot.get("end", 12)
            return f"{start_hour:02d}:00", f"{end_hour:02d}:00"

    # Match by ordinal (first, second, third, 1st, 2nd, 3rd)
    ordinal_map = {
        "first": 0, "1st": 0, "1": 0,
        "second": 1, "2nd": 1, "2": 1,
        "third": 2, "3rd": 2, "3": 2,
        # German ordinals
        "erste": 0, "ersten": 0, "erstes": 0,
        "zweite": 1, "zweiten": 1, "zweites": 1,
        "dritte": 2, "dritten": 2, "drittes": 2,
    }

    if label in ordinal_map:
        idx = ordinal_map[label]
        if idx < len(slots_config):
            slot = slots_config[idx]
            start_hour = slot.get("start", 9)
            end_hour = slot.get("end", 12)
            return f"{start_hour:02d}:00", f"{end_hour:02d}:00"

    logger.debug("[TIME_SLOT] Could not match label '%s' to any slot", label)
    return None


def set_time_slot_pending(
    event_entry: Dict[str, Any],
    date_iso: str,
    date_display: str,
) -> None:
    """Set pending state for time slot selection.

    Args:
        event_entry: Event entry to modify
        date_iso: ISO format date (YYYY-MM-DD)
        date_display: Display format date (e.g., "May 15, 2026")
    """
    slots = get_event_time_slots()
    slot_descriptions = []

    for slot in slots:
        label = slot.get("label", "Unknown")
        start = slot.get("start", 0)
        end = slot.get("end", 0)
        slot_descriptions.append(f"{label} ({start:02d}:00-{end:02d}:00)")

    event_entry["event_time_slot_pending"] = {
        "date_iso": date_iso,
        "date_display": date_display,
        "slots": slot_descriptions,
    }
    logger.info("[TIME_SLOT] Set pending state for %s with slots: %s",
               date_display, slot_descriptions)


def clear_time_slot_pending(event_entry: Dict[str, Any]) -> None:
    """Clear the pending time slot state."""
    removed = event_entry.pop("event_time_slot_pending", None)
    if removed:
        logger.debug("[TIME_SLOT] Cleared pending state")


def get_pending_slot_info(event_entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Get the pending time slot info if any.

    Returns:
        Dict with date_iso, date_display, slots - or None if not pending
    """
    return event_entry.get("event_time_slot_pending")


def build_time_slot_prompt(
    date_display: str,
    slots: List[str],
) -> str:
    """Build a user-friendly prompt for time slot selection.

    Args:
        date_display: The confirmed date in display format
        slots: List of slot descriptions (e.g., ["Morning (09:00-12:00)", ...])

    Returns:
        Formatted prompt string
    """
    slot_list = "\n".join(f"- **{slot}**" for slot in slots)

    return (
        f"Your event date is confirmed for **{date_display}**.\n\n"
        f"Please select your preferred time slot:\n\n"
        f"{slot_list}\n\n"
        f"Just let me know which works best for you!"
    )


__all__ = [
    "is_time_slot_pending",
    "should_prompt_time_slot",
    "parse_slot_from_detection",
    "set_time_slot_pending",
    "clear_time_slot_pending",
    "get_pending_slot_info",
    "build_time_slot_prompt",
]
