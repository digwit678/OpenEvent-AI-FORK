"""
Constants for Step2 Date Confirmation workflow.

Extracted from step2_handler.py for better modularity (D1 refactoring).

Usage:
    from workflows.steps.step2_date_confirmation.trigger.constants import (
        MONTH_NAME_TO_INDEX,
        WEEKDAY_NAME_TO_INDEX,
        AFFIRMATIVE_TOKENS,
        ...
    )
"""

from __future__ import annotations

from typing import Dict, Set, Tuple, List

# -----------------------------------------------------------------------------
# Month/Weekday Name Mappings
# -----------------------------------------------------------------------------

MONTH_NAME_TO_INDEX: Dict[str, int] = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

WEEKDAY_NAME_TO_INDEX: Dict[str, int] = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}

WEEKDAY_LABELS: List[str] = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]

# -----------------------------------------------------------------------------
# Keyword/Token Sets
# -----------------------------------------------------------------------------

PLACEHOLDER_NAMES: Set[str] = {"not", "na", "n/a", "unspecified", "unknown", "client"}

AFFIRMATIVE_TOKENS: Set[str] = {
    "yes",
    "yep",
    "sure",
    "sounds good",
    "that works",
    "works for me",
    "confirm",
    "confirmed",
    "let's do it",
    "go ahead",
    "we agree",
    "all good",
    "perfect",
}

CONFIRMATION_KEYWORDS: Set[str] = {
    "we'll go with",
    "we will go with",
    "we'll take",
    "we will take",
    "we confirm",
    "please confirm",
    "lock in",
    "book it",
    "reserve it",
    "confirm the date",
    "confirming",
    "take the",
    "take ",
}

SIGNATURE_MARKERS: Tuple[str, ...] = (
    "best regards",
    "kind regards",
    "regards",
    "many thanks",
    "thanks",
    "thank you",
    "cheers",
    "beste grüsse",
    "freundliche grüsse",
)

# -----------------------------------------------------------------------------
# Time Hint Defaults
# -----------------------------------------------------------------------------

TIME_HINT_DEFAULTS: Dict[str, Tuple[str, str]] = {
    "morning": ("08:00", "12:00"),
    "afternoon": ("12:00", "17:00"),
    "evening": ("18:00", "22:00"),
}

# -----------------------------------------------------------------------------
# Exports
# -----------------------------------------------------------------------------

__all__ = [
    # Month/weekday mappings
    "MONTH_NAME_TO_INDEX",
    "WEEKDAY_NAME_TO_INDEX",
    "WEEKDAY_LABELS",
    # Keyword sets
    "PLACEHOLDER_NAMES",
    "AFFIRMATIVE_TOKENS",
    "CONFIRMATION_KEYWORDS",
    "SIGNATURE_MARKERS",
    # Time hints
    "TIME_HINT_DEFAULTS",
]
