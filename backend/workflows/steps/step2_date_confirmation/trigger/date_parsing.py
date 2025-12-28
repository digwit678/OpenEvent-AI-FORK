"""
Date parsing utilities for Step2 Date Confirmation workflow.

Extracted from step2_handler.py for better modularity (D2 refactoring).

All functions in this module are pure (no side effects, no DB access).

Usage:
    from backend.workflows.steps.step2_date_confirmation.trigger.date_parsing import (
        safe_parse_iso_date,
        iso_date_is_past,
        normalize_iso_candidate,
        ...
    )
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, List, Optional, Sequence

from backend.workflows.common.datetime_parse import to_iso_date
from backend.workflows.common.timeutils import format_iso_date_to_ddmmyyyy

from .constants import MONTH_NAME_TO_INDEX, WEEKDAY_NAME_TO_INDEX


# -----------------------------------------------------------------------------
# ISO Date Parsing
# -----------------------------------------------------------------------------


def safe_parse_iso_date(iso_value: str) -> Optional[date]:
    """Parse an ISO date string, returning None on failure."""
    try:
        return datetime.fromisoformat(iso_value).date()
    except ValueError:
        return None


def iso_date_is_past(iso_value: str) -> bool:
    """Check if an ISO date string represents a date in the past."""
    try:
        return datetime.fromisoformat(iso_value).date() < date.today()
    except ValueError:
        return True


def normalize_iso_candidate(value: Any) -> Optional[str]:
    """
    Normalize various date formats to ISO YYYY-MM-DD.

    Handles:
    - ISO format with timezone (Z suffix)
    - Partial ISO matches
    - DD.MM.YYYY and other formats via to_iso_date
    """
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).date().isoformat()
    except ValueError:
        pass
    iso_match = re.match(r"(\d{4}-\d{2}-\d{2})", text)
    if iso_match:
        return iso_match.group(1)
    converted = to_iso_date(text)
    if converted:
        return converted
    return None


def next_matching_date(original: date, reference: date) -> date:
    """
    Find the next occurrence of a date (same month/day) after reference.

    Handles leap year edge cases by clamping day to 28 for Feb 29.
    """
    candidate_year = max(reference.year, original.year)
    while True:
        try:
            candidate = original.replace(year=candidate_year)
        except ValueError:
            clamped_day = min(original.day, 28)
            candidate = date(candidate_year, original.month, clamped_day)
        if candidate > reference:
            return candidate
        candidate_year += 1


# -----------------------------------------------------------------------------
# Display Formatting
# -----------------------------------------------------------------------------


def format_display_dates(iso_dates: Sequence[str]) -> List[str]:
    """Convert ISO dates to DD.MM.YYYY display format."""
    labels: List[str] = []
    for iso_value in iso_dates:
        labels.append(format_iso_date_to_ddmmyyyy(iso_value) or iso_value)
    return labels


def human_join(values: Sequence[str]) -> str:
    """
    Join values with natural language connectors.

    Examples:
        ["A"] -> "A"
        ["A", "B"] -> "A and B"
        ["A", "B", "C"] -> "A, B, and C"
    """
    values = [value for value in values if value]
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return ", ".join(values[:-1]) + f", and {values[-1]}"


# -----------------------------------------------------------------------------
# Weekday Parsing
# -----------------------------------------------------------------------------


def clean_weekdays_hint(raw: Any) -> List[int]:
    """
    Clean and validate weekday hints.

    Accepts 1-7 integer values (Monday=1 to Sunday=7).
    """
    cleaned: List[int] = []
    if not isinstance(raw, (list, tuple, set)):
        return cleaned
    for value in raw:
        try:
            hint_int = int(value)
        except (TypeError, ValueError):
            continue
        if 1 <= hint_int <= 7:
            cleaned.append(hint_int)
    return cleaned


def parse_weekday_mentions(text: str) -> set[int]:
    """
    Extract weekday indices (0-6) mentioned in text.

    Scans for weekday names (Monday, Mon, Tuesday, Tue, etc.).
    """
    result: set[int] = set()
    if not text:
        return result
    lowered = text.lower()
    for token, index in WEEKDAY_NAME_TO_INDEX.items():
        if token in lowered:
            result.add(index)
    return result


def weekday_indices_from_hint(hint: Any) -> set[int]:
    """
    Convert weekday hint(s) to set of indices (0-6).

    Accepts string names, lists, or nested structures.
    """
    result: set[int] = set()
    if hint is None:
        return result
    if isinstance(hint, (list, tuple, set)):
        for item in hint:
            result.update(weekday_indices_from_hint(item))
        return result
    token = str(hint).strip().lower()
    if not token:
        return result
    if token in WEEKDAY_NAME_TO_INDEX:
        result.add(WEEKDAY_NAME_TO_INDEX[token])
    return result


# -----------------------------------------------------------------------------
# Month/Weekday Normalization
# -----------------------------------------------------------------------------


def normalize_month_token(value: Optional[str]) -> Optional[int]:
    """Convert month name/abbreviation to month number (1-12)."""
    if not value:
        return None
    token = str(value).strip().lower()
    return MONTH_NAME_TO_INDEX.get(token)


def normalize_weekday_tokens(value: Any) -> List[int]:
    """
    Convert weekday name(s) to sorted list of indices (0-6).

    Accepts single string or collection of strings.
    """
    if value in (None, "", [], ()):
        return []
    if isinstance(value, (list, tuple, set)):
        tokens = [str(item).strip().lower() for item in value if str(item).strip()]
    else:
        tokens = [str(value).strip().lower()]
    indices: List[int] = []
    for token in tokens:
        idx = WEEKDAY_NAME_TO_INDEX.get(token)
        if idx is not None:
            indices.append(idx)
    return sorted(set(indices))


# -----------------------------------------------------------------------------
# Exports
# -----------------------------------------------------------------------------

__all__ = [
    # ISO date parsing
    "safe_parse_iso_date",
    "iso_date_is_past",
    "normalize_iso_candidate",
    "next_matching_date",
    # Display formatting
    "format_display_dates",
    "human_join",
    # Weekday parsing
    "clean_weekdays_hint",
    "parse_weekday_mentions",
    "weekday_indices_from_hint",
    # Month/weekday normalization
    "normalize_month_token",
    "normalize_weekday_tokens",
]
