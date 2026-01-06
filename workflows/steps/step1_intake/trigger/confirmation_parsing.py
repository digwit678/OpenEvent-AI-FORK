"""Confirmation and date/time parsing helpers for Step 1.

Extracted from step1_handler.py as part of I1 refactoring (Dec 2025).
"""
from __future__ import annotations

import re
from datetime import time
from typing import Any, Dict, Optional, Tuple

from backend.workflows.common.datetime_parse import parse_first_date, parse_time_range
from backend.workflows.io.database import load_rooms

# Date/time token patterns
DATE_TOKEN = re.compile(r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\b")

MONTH_TOKENS: Tuple[str, ...] = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)

AFFIRMATIVE_TOKENS: Tuple[str, ...] = (
    "ok",
    "okay",
    "great",
    "sounds good",
    "lets do",
    "let's do",
    "we'll take",
    "lock",
    "confirm",
    "go with",
    "works",
    "take",
)


def extract_confirmation_details(
    text: str, fallback_year: int
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Parse date and time range from confirmation text.

    Returns:
        Tuple of (iso_date, start_time, end_time) where times are "HH:MM" format.
    """
    parsed = parse_first_date(text, fallback_year=fallback_year)
    iso_date = parsed.isoformat() if parsed else None
    start, end, _ = parse_time_range(text)

    def _fmt(value: Optional[time]) -> Optional[str]:
        if not value:
            return None
        return f"{value.hour:02d}:{value.minute:02d}"

    return iso_date, _fmt(start), _fmt(end)


def looks_like_gate_confirmation(
    message_text: str, linked_event: Optional[Dict[str, Any]]
) -> bool:
    """Detect if message looks like a gate confirmation for Step 2.

    Note: This function calls load_rooms() for pattern matching.
    Consider refactoring to accept rooms parameter in future.
    """
    if not linked_event:
        return False
    if linked_event.get("current_step") != 2:
        return False
    thread_state = (linked_event.get("thread_state") or "").lower()
    if thread_state not in {"awaiting client", "awaiting client response", "waiting on hil"}:
        return False

    text = (message_text or "").strip()
    if not text:
        return False
    lowered = text.lower()

    has_date_token = bool(DATE_TOKEN.search(lowered))
    if not has_date_token:
        # handle formats like "07 feb" or "7 february"
        month_hit = any(token in lowered for token in MONTH_TOKENS)
        day_hit = any(str(day) in lowered for day in range(1, 32))
        has_date_token = month_hit and day_hit

    if not has_date_token:
        return False

    if any(token in lowered for token in AFFIRMATIVE_TOKENS):
        return True

    # plain date replies like "07.02.2026" or "2026-02-07"
    stripped_digits = lowered.replace(" ", "")
    if stripped_digits.replace(".", "").replace("-", "").replace("/", "").isdigit():
        return True

    # short replies with date plus punctuation
    if len(lowered.split()) <= 6 and has_date_token:
        return True

    return False
