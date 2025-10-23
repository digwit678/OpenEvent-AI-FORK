"""Requirement helpers with small caches for deterministic hashing.

Tests can call `clear_hash_caches()` to reset the in-memory caches between
scenarios.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict

from backend.workflows.io.database import append_audit_entry
from backend.utils import json_io

_STABLE_HASH_CACHE: Dict[str, str] = {}
_CACHE_LIMIT = 256


REQUIREMENT_KEYS = [
    "number_of_participants",
    "seating_layout",
    "event_duration",
    "special_requirements",
    "preferred_room",
]


def build_requirements(user_info: Dict[str, Any]) -> Dict[str, Any]:
    """[Condition] Canonicalise requirement-related fields from user info."""

    participants = user_info.get("participants")
    seating_layout = user_info.get("layout") or user_info.get("type")
    event_duration = {
        "start": user_info.get("start_time"),
        "end": user_info.get("end_time"),
    }
    if not event_duration["start"] and not event_duration["end"]:
        event_duration = {}
    special_requirements = user_info.get("notes")
    preferred_room = user_info.get("room")
    requirements = {
        "number_of_participants": participants,
        "seating_layout": seating_layout,
        "event_duration": event_duration,
        "special_requirements": special_requirements,
        "preferred_room": preferred_room,
    }
    return {key: requirements.get(key) for key in REQUIREMENT_KEYS}


def stable_hash(payload: Any) -> str:
    """[Condition] Produce a stable SHA256 hash for arbitrary JSON-serialisable data."""

    normalized = json_io.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    cached = _STABLE_HASH_CACHE.get(normalized)
    if cached is not None:
        return cached
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    if len(_STABLE_HASH_CACHE) >= _CACHE_LIMIT:
        _STABLE_HASH_CACHE.clear()
    _STABLE_HASH_CACHE[normalized] = digest
    return digest


def requirements_hash(requirements: Dict[str, Any]) -> str:
    """[Condition] Hash requirements using canonical order."""

    subset = {key: requirements.get(key) for key in REQUIREMENT_KEYS}
    return stable_hash(subset)


def merge_client_profile(event_entry: Dict[str, Any], incoming: Dict[str, Any]) -> bool:
    """
    Merge non-structural client profile fields into event_data.

    Returns True when any field changes so callers can persist the event entry.
    """

    if not event_entry or not incoming:
        return False

    normalised_incoming: Dict[str, Any] = {}
    for key, value in incoming.items():
        if value is None:
            continue
        key_str = str(key).strip().lower()
        if not key_str:
            continue
        normalised_incoming[key_str] = value

    if not normalised_incoming:
        return False

    profile_keys = {
        "Name": ["name"],
        "Email": ["email"],
        "Phone": ["phone", "telephone"],
        "Company": ["company"],
        "Billing Address": ["billing_address", "billing address", "address"],
        "Language": ["language", "lang"],
    }

    event_data = event_entry.setdefault("event_data", {})
    changed_fields: list[str] = []

    for canonical, aliases in profile_keys.items():
        search_keys = [canonical] + aliases
        found = None
        for alias in search_keys:
            alias_key = str(alias).strip().lower()
            if not alias_key:
                continue
            if alias_key in normalised_incoming:
                candidate = normalised_incoming[alias_key]
                if candidate not in ("", None):
                    found = candidate
                    break
        if found is not None and event_data.get(canonical) != found:
            event_data[canonical] = found
            changed_fields.append(canonical)

    if not changed_fields:
        return False

    current_step = event_entry.get("current_step")
    if not isinstance(current_step, int):
        current_step = 0
    append_audit_entry(event_entry, current_step, current_step, "info_update")
    if event_entry.get("audit"):
        event_entry["audit"][-1]["fields"] = changed_fields
    return True


def clear_hash_caches() -> None:
    """Reset stable hash caches (used by tests)."""

    _STABLE_HASH_CACHE.clear()
