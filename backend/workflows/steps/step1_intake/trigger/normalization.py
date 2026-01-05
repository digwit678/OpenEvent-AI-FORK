"""
Pure text normalization utilities for Step1 intake processing.

Extracted from step1_handler.py for better modularity (I1 refactoring).
These functions have NO side effects: no DB access, no state mutation.
"""

import re


def normalize_quotes(text: str) -> str:
    """Normalize typographic apostrophes/quotes for downstream keyword checks."""

    if not text:
        return ""
    return (
        text.replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u00a0", " ")
    )


def normalize_room_token(value: str) -> str:
    """Normalize a room token for comparison (lowercase, alphanumeric only)."""

    return re.sub(r"[^a-z0-9]", "", value.lower())


__all__ = [
    "normalize_quotes",
    "normalize_room_token",
]
