"""
Date Context Resolution Module (D-CTX extraction from step2_handler.py)

Extracted: 2026-01-23
Purpose: Resolve date preferences, hints, and anchors from user context.

This module handles:
- Parsing requested dates from state
- Resolving weekday preferences
- Resolving time hints
- Resolving anchor dates for candidate generation
"""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Dict, List, Optional, Set, Tuple

from .date_parsing import (
    safe_parse_iso_date,
    parse_weekday_mentions,
    weekday_indices_from_hint,
)
from .step2_utils import _normalize_time_value, _to_time


def parse_requested_dates(
    requested_dates: List[str],
) -> Tuple[List[date], Optional[date], Set[int]]:
    """
    Parse requested dates and extract date objects, minimum date, and preferred weekdays.

    Args:
        requested_dates: List of ISO date strings

    Returns:
        Tuple of (date_objects, min_date, preferred_weekdays)
    """
    date_objs = [safe_parse_iso_date(value) for value in requested_dates]
    date_objs = [value for value in date_objs if value]

    min_date = min(date_objs) if date_objs else None
    preferred_weekdays = {value.weekday() for value in date_objs}

    return date_objs, min_date, preferred_weekdays


def resolve_weekday_preferences(
    user_text: str,
    user_info: Dict[str, Any],
    event_entry: Dict[str, Any],
    initial_weekdays: Optional[Set[int]] = None,
) -> Set[int]:
    """
    Resolve preferred weekdays from user text and hints.

    Args:
        user_text: Combined subject + body text
        user_info: User info dict with vague_weekday hint
        event_entry: Event entry dict with vague_weekday fallback
        initial_weekdays: Initial weekday preferences (from requested dates)

    Returns:
        Set of weekday indices (0=Monday, 6=Sunday)
    """
    preferred = set(initial_weekdays or set())

    if not preferred:
        preferred = parse_weekday_mentions(user_text)

    if not preferred:
        hint = user_info.get("vague_weekday") or event_entry.get("vague_weekday")
        preferred = weekday_indices_from_hint(hint)

    return preferred


def resolve_time_hints(
    user_info: Dict[str, Any],
    default_start: str = "18:00",
    default_end: str = "22:00",
) -> Tuple[Optional[str], Optional[str], Optional[time], Optional[time]]:
    """
    Resolve time hints from user info.

    Args:
        user_info: User info dict with start_time/end_time
        default_start: Default start time if not specified
        default_end: Default end time if not specified

    Returns:
        Tuple of (start_hint, end_hint, start_time_obj, end_time_obj)
    """
    start_hint = _normalize_time_value(user_info.get("start_time"))
    end_hint = _normalize_time_value(user_info.get("end_time"))

    start_pref = start_hint or default_start
    end_pref = end_hint or default_end

    try:
        start_time_obj = _to_time(start_pref)
        end_time_obj = _to_time(end_pref)
    except ValueError:
        start_time_obj = None
        end_time_obj = None

    return start_hint, end_hint, start_time_obj, end_time_obj


def resolve_anchor_date(
    user_text: str,
    reference_day: date,
    requested_dates: List[str],
    focus_iso: Optional[str] = None,
) -> Tuple[Optional[date], Optional[datetime]]:
    """
    Resolve the anchor date for candidate generation.

    Priority:
    1. focus_iso if provided
    2. Parsed from user_text
    3. First requested date

    Args:
        user_text: Combined subject + body text
        reference_day: Reference date for parsing
        requested_dates: List of ISO date strings
        focus_iso: Optional explicit focus date

    Returns:
        Tuple of (anchor_date, anchor_datetime)
    """
    from workflows.common.datetime_parse import parse_first_date

    anchor = parse_first_date(
        user_text,
        fallback_year=reference_day.year,
        reference=reference_day,
    )

    if not anchor and requested_dates:
        try:
            anchor = datetime.fromisoformat(requested_dates[0]).date()
        except ValueError:
            anchor = None

    if focus_iso:
        try:
            anchor = datetime.fromisoformat(focus_iso).date()
        except ValueError:
            pass

    anchor_dt = datetime.combine(anchor, time(hour=12)) if anchor else None
    return anchor, anchor_dt


def calculate_collection_limits(
    reason: Optional[str],
    attempt: int,
    preferred_weekdays: Set[int],
    base_limit: int = 5,
) -> Tuple[int, int]:
    """
    Calculate limits for candidate date collection.

    Args:
        reason: Optional reason string (e.g., "past date")
        attempt: Current attempt number
        preferred_weekdays: Set of preferred weekday indices
        base_limit: Base limit for candidates

    Returns:
        Tuple of (limit, collection_cap)
    """
    limit = 4 if reason and "past" in (reason or "").lower() else base_limit
    if attempt > 1 and limit < base_limit:
        limit = base_limit

    collection_cap = limit if not preferred_weekdays else max(limit * 3, limit + 5)

    return limit, collection_cap


def get_preferred_room(event_entry: Dict[str, Any]) -> str:
    """Get the preferred room from event requirements."""
    requirements = event_entry.get("requirements") or {}
    return requirements.get("preferred_room") or "Not specified"
