"""
Step 3 Room Ranking and Selection Functions.

Extracted from step3_handler.py as part of R7 refactoring (Jan 2026).

This module contains:
- _select_room: Select top-ranked available room
- _build_ranked_rows: Build ranked room rows with actions
- _derive_hint: Generate hint text for room
- _needs_better_room_alternatives: Check if better room options needed
- _has_explicit_preferences: Check if user has explicit preferences
- _room_requirements_payload: Build requirements payload for room
- _available_dates_for_rooms: Get available dates per room
- _extract_participants: Extract participant count from requirements

Usage:
    from .room_ranking import (
        select_room,
        build_ranked_rows,
        needs_better_room_alternatives,
    )
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from workflows.common.sorting import RankedRoom
from workflows.common.timeutils import format_iso_date_to_ddmmyyyy

from ..condition.decide import room_status_on_date
from .constants import (
    ROOM_OUTCOME_UNAVAILABLE,
    ROOM_OUTCOME_AVAILABLE,
    ROOM_OUTCOME_OPTION,
    ROOM_SIZE_ORDER,
)


# -----------------------------------------------------------------------------
# Room Selection
# -----------------------------------------------------------------------------


def select_room(ranked: List[RankedRoom]) -> Optional[RankedRoom]:
    """Return the top-ranked room that's available or on option AND fits capacity.

    The ranking already incorporates status weight (Available=60, Option=35)
    plus preferred_room bonus (30 points). We prioritize rooms that fit the
    requested capacity (capacity_ok=True) over rooms that don't fit.

    Selection priority:
    1. First Available/Option room that FITS capacity
    2. First Available/Option room (even if over-capacity) - fallback
    3. First room in the list - last resort
    """
    # First pass: find a room that fits AND is available
    for entry in ranked:
        if entry.status in (ROOM_OUTCOME_AVAILABLE, ROOM_OUTCOME_OPTION) and entry.capacity_ok:
            return entry

    # Second pass: any available room (even if doesn't fit - user may adjust)
    for entry in ranked:
        if entry.status in (ROOM_OUTCOME_AVAILABLE, ROOM_OUTCOME_OPTION):
            return entry

    return ranked[0] if ranked else None


# -----------------------------------------------------------------------------
# Room Ranking Rows
# -----------------------------------------------------------------------------


def build_ranked_rows(
    chosen_date: str,
    ranked: List[RankedRoom],
    preferences: Optional[Dict[str, Any]],
    available_dates_map: Dict[str, List[str]],
    room_profiles: Dict[str, Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Build ranked room rows with associated actions."""
    rows: List[Dict[str, Any]] = []
    actions: List[Dict[str, Any]] = []
    explicit_prefs = has_explicit_preferences(preferences)

    for entry in ranked:
        hint_label = derive_hint(entry, preferences, explicit_prefs)
        available_dates = available_dates_map.get(entry.room, [])
        requirements_info = room_requirements_payload(entry) if explicit_prefs else {"matched": [], "missing": []}
        profile = room_profiles.get(entry.room, {})
        badges = profile.get("requirements_badges") or {}
        row = {
            "date": chosen_date,
            "room": entry.room,
            "status": entry.status,
            "hint": hint_label,
            "requirements_score": round(profile.get("requirements_score", entry.score), 2),
            "available_dates": available_dates,
            "requirements": requirements_info,
            "coffee_match": profile.get("coffee_badge"),
            "u_shape_match": badges.get("u-shape"),
            "projector_match": badges.get("projector"),
        }
        rows.append(row)
        if entry.status in {ROOM_OUTCOME_AVAILABLE, ROOM_OUTCOME_OPTION}:
            actions.append(
                {
                    "type": "select_room",
                    "label": f"Proceed with {entry.room} ({hint_label})",
                    "room": entry.room,
                    "date": chosen_date,
                    "status": entry.status,
                    "hint": hint_label,
                    "available_dates": available_dates,
                    "requirements": dict(requirements_info),
                }
            )

    return rows, actions


# -----------------------------------------------------------------------------
# Room Hints and Preferences
# -----------------------------------------------------------------------------


def derive_hint(entry: Optional[RankedRoom], preferences: Optional[Dict[str, Any]], explicit: bool) -> str:
    """Generate hint text describing room match quality."""
    if not entry:
        return "No room selected"
    matched = [item for item in entry.matched if item]
    if matched:
        return ", ".join(matched[:3])
    # Show closest matches (partial/similar products) if no exact matches
    closest = [item for item in entry.closest if item]
    if closest:
        # Extract just the product name from "Classic Apero (closest to dinner)" format
        clean_closest = [item.split(" (closest")[0] for item in closest]
        return ", ".join(clean_closest[:3])
    if explicit:
        missing = [item for item in entry.missing if item]
        if missing:
            return f"Missing: {', '.join(missing[:3])}"
        base_hint = (entry.hint or "").strip()
        if base_hint and base_hint.lower() != "products available":
            return base_hint[0].upper() + base_hint[1:]
        return "No preference match"
    base_hint = (entry.hint or "").strip()
    if base_hint and base_hint.lower() != "products available":
        return base_hint[0].upper() + base_hint[1:]
    return "Available"


def has_explicit_preferences(preferences: Optional[Dict[str, Any]]) -> bool:
    """Check if user has explicit product/keyword preferences."""
    if not isinstance(preferences, dict):
        return False
    wish_products = preferences.get("wish_products")
    if isinstance(wish_products, (list, tuple)):
        for item in wish_products:
            if isinstance(item, str) and item.strip():
                return True
    keywords = preferences.get("keywords")
    if isinstance(keywords, (list, tuple)):
        for item in keywords:
            if isinstance(item, str) and item.strip():
                return True
    return False


def room_requirements_payload(entry: RankedRoom) -> Dict[str, List[str]]:
    """Build requirements payload for a room entry."""
    return {
        "matched": list(entry.matched),
        "closest": list(entry.closest),  # Moderate matches with context
        "missing": list(entry.missing),
    }


# -----------------------------------------------------------------------------
# Better Alternatives Check
# -----------------------------------------------------------------------------


def needs_better_room_alternatives(
    user_info: Dict[str, Any],
    status_map: Dict[str, str],
    event_entry: Dict[str, Any],
) -> bool:
    """Check if we need to offer better/larger room alternatives."""
    if (user_info or {}).get("room_feedback") != "not_good_enough":
        return False

    requirements = event_entry.get("requirements") or {}
    baseline_room = event_entry.get("locked_room_id") or requirements.get("preferred_room")
    baseline_rank = ROOM_SIZE_ORDER.get(str(baseline_room), 0)
    if baseline_rank == 0:
        return True

    larger_available = False
    for room_name, status in status_map.items():
        if ROOM_SIZE_ORDER.get(room_name, 0) > baseline_rank and status == ROOM_OUTCOME_AVAILABLE:
            larger_available = True
            break

    if not larger_available:
        return True

    participants = (requirements.get("number_of_participants") or 0)
    participants_val: Optional[int]
    try:
        participants_val = int(participants)
    except (TypeError, ValueError):
        participants_val = None

    capacity_map = {
        1: 36,
        2: 54,
        3: 96,
        4: 140,
    }
    if participants_val is not None:
        baseline_capacity = capacity_map.get(baseline_rank)
        if baseline_capacity and participants_val > baseline_capacity:
            return True

    return False


# -----------------------------------------------------------------------------
# Date Availability
# -----------------------------------------------------------------------------


def available_dates_for_rooms(
    db: Dict[str, Any],
    ranked: List[RankedRoom],
    candidate_iso_dates: List[str],
    participants: Optional[int],
) -> Dict[str, List[str]]:
    """Get available dates for each ranked room."""
    availability: Dict[str, List[str]] = {}
    for entry in ranked:
        dates: List[str] = []
        for iso_date in candidate_iso_dates:
            display_date = format_iso_date_to_ddmmyyyy(iso_date)
            if not display_date:
                continue
            status = room_status_on_date(db, display_date, entry.room)
            if status.lower() in {"available", "option"}:
                dates.append(iso_date)
        availability[entry.room] = dates
    return availability


def dates_in_month_weekday_wrapper(
    month_hint: Optional[Any],
    weekday_hint: Optional[Any],
    *,
    limit: int,
) -> List[str]:
    """Wrapper for dates module dates_in_month_weekday."""
    from workflows.io import dates as dates_module

    return dates_module.dates_in_month_weekday(month_hint, weekday_hint, limit=limit)


def closest_alternatives_wrapper(
    anchor_iso: str,
    weekday_hint: Optional[Any],
    month_hint: Optional[Any],
    *,
    limit: int,
) -> List[str]:
    """Wrapper for dates module closest_alternatives."""
    from workflows.io import dates as dates_module

    return dates_module.closest_alternatives(anchor_iso, weekday_hint, month_hint, limit=limit)


# -----------------------------------------------------------------------------
# Participant Extraction
# -----------------------------------------------------------------------------


def extract_participants(requirements: Dict[str, Any]) -> Optional[int]:
    """Extract participant count from requirements dict."""
    raw = requirements.get("number_of_participants")
    if raw in (None, "", "Not specified", "none"):
        raw = requirements.get("participants")
    if raw in (None, "", "Not specified", "none"):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


# -----------------------------------------------------------------------------
# Backward-compatible aliases (prefixed with underscore)
# -----------------------------------------------------------------------------

# For imports that expect underscore-prefixed names
_select_room = select_room
_build_ranked_rows = build_ranked_rows
_derive_hint = derive_hint
_has_explicit_preferences = has_explicit_preferences
_room_requirements_payload = room_requirements_payload
_needs_better_room_alternatives = needs_better_room_alternatives
_available_dates_for_rooms = available_dates_for_rooms
_dates_in_month_weekday_wrapper = dates_in_month_weekday_wrapper
_closest_alternatives_wrapper = closest_alternatives_wrapper
_extract_participants = extract_participants


# -----------------------------------------------------------------------------
# Exports
# -----------------------------------------------------------------------------

__all__ = [
    # Public names
    "select_room",
    "build_ranked_rows",
    "derive_hint",
    "has_explicit_preferences",
    "room_requirements_payload",
    "needs_better_room_alternatives",
    "available_dates_for_rooms",
    "dates_in_month_weekday_wrapper",
    "closest_alternatives_wrapper",
    "extract_participants",
    # Backward-compatible underscore aliases
    "_select_room",
    "_build_ranked_rows",
    "_derive_hint",
    "_has_explicit_preferences",
    "_room_requirements_payload",
    "_needs_better_room_alternatives",
    "_available_dates_for_rooms",
    "_dates_in_month_weekday_wrapper",
    "_closest_alternatives_wrapper",
    "_extract_participants",
]
