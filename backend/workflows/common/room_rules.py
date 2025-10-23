from __future__ import annotations

from datetime import datetime, timedelta
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
    "room_feedback",
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


def site_visit_allowed(event_entry: dict) -> bool:
    """Return whether site visits are permitted for the current event configuration."""

    policy = event_entry.get("policy") or {}
    allow_site_visit = policy.get("allow_site_visit", True)
    return bool(allow_site_visit) and bool(event_entry.get("locked_room_id"))


def find_better_room_dates(event_entry: dict) -> list[str]:
    """
    Deterministic stub using current requirements/locked_room_id/chosen_date.
    Return up to 3 ISO dates within the next ~60 days where a larger/better room is available.
    """

    chosen_date = event_entry.get("chosen_date")
    if not chosen_date:
        return []
    try:
        base_date = datetime.strptime(chosen_date, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        try:
            base_date = datetime.strptime(chosen_date, "%d.%m.%Y").date()
        except (TypeError, ValueError):
            return []

    requirements = event_entry.get("requirements") or {}
    participants = requirements.get("number_of_participants")
    participant_seed = 0
    if isinstance(participants, int):
        participant_seed = participants
    elif participants is not None:
        try:
            participant_seed = int(str(participants))
        except (TypeError, ValueError):
            participant_seed = 0

    locked_room = event_entry.get("locked_room_id") or requirements.get("preferred_room") or ""
    room_seed = sum(ord(ch) for ch in str(locked_room))
    seed = (participant_seed + room_seed) % 5

    offsets = [14, 21, 26, 28, 35, 42, 49, 56]
    rotated_offsets = offsets[seed:] + offsets[:seed]
    horizon = base_date + timedelta(days=60)

    alt_dates: list[str] = []
    for offset in rotated_offsets:
        candidate = base_date + timedelta(days=offset)
        if candidate > horizon:
            continue
        alt_dates.append(candidate.isoformat())
        if len(alt_dates) == 3:
            break
    return alt_dates
