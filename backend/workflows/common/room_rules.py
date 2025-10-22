from __future__ import annotations

import re
from typing import Any, Optional


ROOM_ALIASES = {
    "punkt.null": "Punkt.Null",
    "punktnull": "Punkt.Null",
    "room a": "Room A",
    "room b": "Room B",
    "room c": "Room C",
}

LANGUAGE_ALIASES = {
    "english": "en",
    "german": "de",
    "french": "fr",
    "italian": "it",
    "spanish": "es",
}

USER_INFO_KEYS = [
    "date",
    "start_time",
    "end_time",
    "city",
    "participants",
    "room",
    "name",
    "email",
    "type",
    "catering",
    "phone",
    "company",
    "language",
    "notes",
    "billing_address",
    "hil_approve_step",
    "hil_decision",
    "products_add",
    "products_remove",
]


def clean_text(value: Any, trailing: str = "") -> Optional[str]:
    """[Condition] Normalize arbitrary values into trimmed text snippets."""

    if value is None:
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not value.is_integer():
            text = f"{value}"
        else:
            text = str(int(value))
    else:
        text = str(value)
    cleaned = text.strip()
    if trailing:
        cleaned = cleaned.rstrip(trailing)
    return cleaned or None


def normalize_phone(value: Any) -> Optional[str]:
    """[Condition] Reduce phone numbers to dialable digit sequences."""

    if value is None:
        return None
    text = clean_text(value) or ""
    if not text:
        return None
    digits = re.sub(r"[^\d+]", "", text)
    return digits or text


def sanitize_participants(value: Any) -> Optional[int]:
    """[Condition] Coerce participant counts into integers when present."""

    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = clean_text(value) or ""
    match = re.search(r"(\d{1,4})", text)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None


def normalize_room(token: Any) -> Optional[str]:
    """[Condition] Normalize preferred room naming so it matches inventory terms."""

    if token is None:
        return None
    cleaned = clean_text(token) or ""
    if not cleaned:
        return None
    lower = cleaned.lower()
    key_variants = {
        lower,
        lower.replace(" ", ""),
        lower.replace(".", ""),
    }
    for key in key_variants:
        if key in ROOM_ALIASES:
            return ROOM_ALIASES[key]
    if lower.startswith("room"):
        suffix = cleaned[4:].strip()
        if suffix:
            suffix_norm = suffix.upper() if len(suffix) == 1 else suffix.title()
            return f"Room {suffix_norm}"
        return "Room"
    return cleaned


def normalize_language(token: Optional[Any]) -> Optional[str]:
    """[Condition] Normalize language preferences to standardized locale codes."""

    if token is None:
        return None
    cleaned = clean_text(token, trailing=" .;")
    if not cleaned:
        return None
    lowered = cleaned.lower()
    if lowered in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[lowered]
    if lowered in {"en", "de", "fr", "it", "es"}:
        return lowered
    return cleaned
