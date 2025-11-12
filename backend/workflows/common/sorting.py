from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from backend.services.products import ProductRecord, list_product_records
from backend.workflows.groups.room_availability.db_pers import load_rooms_config

ROOM_OUTCOME_AVAILABLE = "Available"
ROOM_OUTCOME_OPTION = "Option"
ROOM_OUTCOME_UNAVAILABLE = "Unavailable"

_WORD_NORMALISER = re.compile(r"[^a-z0-9]+")


@dataclass
class RankedRoom:
    room: str
    status: str
    score: float
    hint: str
    capacity_ok: bool


@dataclass(frozen=True)
class _RoomEntry:
    label: str
    type: str  # "product" or "feature"
    synonyms: Tuple[str, ...]


@dataclass(frozen=True)
class _PreferenceTerm:
    raw: str
    normalized: str
    weight: float


def rank_rooms(
    status_map: Dict[str, str],
    *,
    preferred_room: Optional[str] = None,
    pax: Optional[int] = None,
    preferences: Optional[Dict[str, Any]] = None,
) -> List[RankedRoom]:
    """Rank rooms by availability, capacity fit, and preference similarity."""

    config_map = _config_by_name()
    entries_map = _room_entries()
    preferred_lower = (preferred_room or "").strip().lower()
    terms = _collect_terms(preferences)
    wish_products = list((preferences or {}).get("wish_products") or [])
    default_hint = str((preferences or {}).get("default_hint") or "Products available")

    ranked: List[RankedRoom] = []

    for room, status in status_map.items():
        key = room.strip().lower()
        config = config_map.get(key, {})
        capacity_value = _capacity_score(config, pax)
        preference_value, hint = _preference_score(entries_map.get(key, ()), terms, default_hint, wish_products)
        preferred_bonus = 10.0 if key and key == preferred_lower else 0.0
        status_score = _status_weight(status)
        total = status_score + capacity_value + preference_value + preferred_bonus
        capacity_ok = capacity_value >= 30.0
        ranked.append(
            RankedRoom(
                room=room,
                status=status,
                score=total,
                hint=hint,
                capacity_ok=capacity_ok,
            )
        )

    ranked.sort(key=lambda entry: (-entry.score, entry.room.lower()))
    return ranked


@lru_cache(maxsize=1)
def _config_by_name() -> Dict[str, Dict[str, Any]]:
    rooms = load_rooms_config()
    config: Dict[str, Dict[str, Any]] = {}
    for entry in rooms:
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        config[name.lower()] = entry
    return config


@lru_cache(maxsize=1)
def _room_entries() -> Dict[str, Tuple[_RoomEntry, ...]]:
    config_map = _config_by_name()
    product_records = list_product_records()

    entries: Dict[str, List[_RoomEntry]] = {name: [] for name in config_map}

    for name, config in config_map.items():
        features = config.get("features") or []
        for feature in features:
            label = str(feature).strip()
            if not label:
                continue
            entries[name].append(_RoomEntry(label=label.title(), type="feature", synonyms=_feature_aliases(label)))

    for record in product_records:
        _attach_product_entries(entries, config_map, record)

    return {name: tuple(items) for name, items in entries.items()}


def _attach_product_entries(
    entries: Dict[str, List[_RoomEntry]],
    config_map: Dict[str, Dict[str, Any]],
    record: ProductRecord,
) -> None:
    unavailable = {value.strip().lower() for value in record.unavailable_in}
    aliases = _product_aliases(record)

    for name, config in config_map.items():
        room_id = str(config.get("id") or "").strip().lower()
        if room_id and room_id in unavailable:
            continue
        entries[name].append(_RoomEntry(label=record.name, type="product", synonyms=aliases))


def _product_aliases(record: ProductRecord) -> Tuple[str, ...]:
    aliases = {record.name.strip().lower()}
    for synonym in record.synonyms:
        lowered = synonym.strip().lower()
        if lowered:
            aliases.add(lowered)
    base = record.name.lower()
    aliases.add(base.replace("&", "and"))
    aliases.add(base.replace("-", " "))
    aliases.add(_normalise_text(base))
    return tuple(sorted({alias for alias in aliases if alias}))


def _feature_aliases(label: str) -> Tuple[str, ...]:
    canonical = label.strip().lower()
    lookup = {
        "stage": {"podium", "raised platform"},
        "projector": {"beamer", "projection"},
        "screen": {"projector screen", "display"},
        "sound_system": {"audio system", "speakers", "pa"},
        "parking": {"parking spots", "parking nearby"},
        "hybrid": {"streaming", "hybrid kit"},
    }
    aliases = lookup.get(canonical, set())
    derived = {
        canonical.replace("_", " "),
        canonical.replace("-", " "),
        _normalise_text(canonical),
    }
    all_aliases = {alias for alias in (*aliases, *derived) if alias}
    return tuple(sorted(all_aliases))


def _collect_terms(preferences: Optional[Dict[str, Any]]) -> List[_PreferenceTerm]:
    if not preferences:
        return []
    terms: List[_PreferenceTerm] = []
    for wish in preferences.get("wish_products") or []:
        normalized = _normalise_text(wish)
        if not normalized:
            continue
        terms.append(_PreferenceTerm(raw=wish, normalized=normalized, weight=1.2))
    for keyword in preferences.get("keywords") or []:
        normalized = _normalise_text(keyword)
        if not normalized:
            continue
        terms.append(_PreferenceTerm(raw=keyword, normalized=normalized, weight=0.9))
    return terms


def _preference_score(
    entries: Sequence[_RoomEntry],
    terms: Sequence[_PreferenceTerm],
    default_hint: str,
    wish_products: Sequence[str],
) -> Tuple[float, str]:
    if not entries or not terms:
        return 0.0, default_hint

    matches: List[Tuple[_PreferenceTerm, _RoomEntry, float]] = []
    for term in terms:
        entry, score = _best_match(term.normalized, entries)
        if entry and score >= 0.55:
            matches.append((term, entry, score))

    if not matches:
        fallback = wish_products[0] if wish_products else default_hint
        return 0.0, fallback

    total = 0.0
    seen: set[Tuple[str, str]] = set()
    for term, entry, score in matches:
        key = (entry.label.lower(), entry.type)
        if key in seen and term.weight < 1.0:
            continue
        seen.add(key)
        total += score * term.weight * 12.0

    matches.sort(key=lambda item: (item[2], item[1].type == "product"), reverse=True)
    top_term, top_entry, _ = matches[0]
    if top_entry.type == "product":
        hint = top_entry.label
    elif wish_products:
        hint = wish_products[0]
    else:
        hint = f"Feature: {top_entry.label}"
    return total, hint


def _best_match(term: str, entries: Sequence[_RoomEntry]) -> Tuple[Optional[_RoomEntry], float]:
    best_entry: Optional[_RoomEntry] = None
    best_score = 0.0
    for entry in entries:
        score = _entry_similarity(term, entry)
        if score > best_score:
            best_score = score
            best_entry = entry
    return best_entry, best_score


def _entry_similarity(term: str, entry: _RoomEntry) -> float:
    candidates = [entry.label]
    candidates.extend(entry.synonyms)
    scores = [_similarity(term, _normalise_text(candidate)) for candidate in candidates if candidate]
    return max(scores) if scores else 0.0


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.92
    ratio = SequenceMatcher(None, a, b).ratio()
    tokens_a = a.split()
    tokens_b = b.split()
    if tokens_a and tokens_b:
        set_a = set(tokens_a)
        set_b = set(tokens_b)
        overlap = len(set_a & set_b) / len(set_a | set_b)
        if overlap:
            ratio = max(ratio, min(1.0, overlap + 0.2))
    return ratio


def _status_weight(status: str) -> int:
    lookup = {
        ROOM_OUTCOME_AVAILABLE: 60,
        ROOM_OUTCOME_OPTION: 35,
        ROOM_OUTCOME_UNAVAILABLE: 5,
    }
    return lookup.get(status, 0)


def _capacity_score(config: Dict[str, Any], pax: Optional[int]) -> float:
    if pax is None:
        return 25.0
    capacity_min = config.get("capacity_min")
    capacity_max = config.get("capacity_max")
    if not isinstance(capacity_min, (int, float)) or not isinstance(capacity_max, (int, float)):
        return 20.0
    if capacity_min <= pax <= capacity_max:
        return 35.0
    if pax < capacity_min:
        return max(8.0 - (capacity_min - pax) * 0.5, 0)
    return max(6.0 - (pax - capacity_max) * 0.5, 0)


def _normalise_text(value: str) -> str:
    lowered = (value or "").strip().lower()
    cleaned = _WORD_NORMALISER.sub(" ", lowered)
    cleaned = cleaned.replace("&", "and")
    return re.sub(r"\s+", " ", cleaned).strip()
