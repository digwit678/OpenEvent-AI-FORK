"""
Date fallback utilities for Step1 intake processing.

Extracted from step1_handler.py for better modularity (I1 refactoring).
These functions have NO side effects: no DB access, no state mutation.
"""

from datetime import datetime
from typing import Optional


def fallback_year_from_ts(ts: Optional[str]) -> int:
    """
    Extract year from a timestamp string for date fallback resolution.

    Used when a date is missing a year component - we infer it from
    the message timestamp. Returns current UTC year if no valid timestamp.
    """

    if not ts:
        return datetime.utcnow().year
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).year
    except ValueError:
        return datetime.utcnow().year


__all__ = [
    "fallback_year_from_ts",
]
