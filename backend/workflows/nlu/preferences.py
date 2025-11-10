from __future__ import annotations

import difflib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from backend.services.products import list_product_records

PreferencePayload = Dict[str, Any]


def extract_preferences(user_info: Dict[str, Any]) -> Optional[PreferencePayload]:
    """
    Normalise structured product/menu preferences captured during intake and
    derive quick room recommendations so downstream steps can reuse them.
    """

    if not isinstance(user_info, dict):
        return None

    wish_products = _collect_wish_products(user_info)
    keywords = _collect_keywords(user_info, wish_products)

    if not wish_products and not keywords:
        return None

    preferences: PreferencePayload = {
        "wish_products": wish_products,
        "keywords": keywords,
        "default_hint": wish_products[0] if wish_products else "Products available",
    }

    if wish_products:
        recommendations = _score_rooms_by_products(wish_products)
        if recommendations:
            preferences["room_recommendations"] = recommendations
            preferences["room_similarity"] = {entry["room"]: entry["score"] for entry in recommendations}
            preferences["room_match_breakdown"] = {
                entry["room"]: {"matched": entry["matched"], "missing": entry["missing"]}
                for entry in recommendations
            }

    return preferences


def _collect_wish_products(user_info: Dict[str, Any]) -> List[str]:
    result: List[str] = []

    def _append(values: Iterable[str]) -> None:
        for value in values:
            cleaned = value.strip()
            if cleaned and cleaned.lower() not in {"none", "not specified"} and cleaned not in result:
                result.append(cleaned)

    raw_wishes = user_info.get("wish_products")
    _append(_normalise_sequence(raw_wishes))

    products_add = user_info.get("products_add")
    if isinstance(products_add, list):
        extracted: List[str] = []
        for entry in products_add:
            if isinstance(entry, dict) and entry.get("name"):
                extracted.append(str(entry["name"]))
            elif isinstance(entry, str):
                extracted.append(entry)
        _append(extracted)

    catering_pref = user_info.get("catering")
    if isinstance(catering_pref, str) and catering_pref.strip():
        _append([catering_pref])

    return result[:10]


def _collect_keywords(user_info: Dict[str, Any], wish_products: Sequence[str]) -> List[str]:
    tokens: List[str] = []

    def _extend(text: Optional[Any]) -> None:
        if not text:
            return
        for token in _tokenize(str(text)):
            if len(token) >= 3 and token not in tokens:
                tokens.append(token)

    for wish in wish_products:
        _extend(wish)

    for field in ("notes", "catering", "layout", "type"):
        _extend(user_info.get(field))

    return tokens[:20]


def _normalise_sequence(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        chunks = re.split(r"[,\n;]+", value)
        return [chunk.strip() for chunk in chunks if chunk.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _score_rooms_by_products(wish_products: Sequence[str]) -> List[Dict[str, Any]]:
    catalog = _room_catalog()
    recommendations: List[Dict[str, Any]] = []

    for room, data in catalog.items():
        phrases = data["phrases"]
        score = 0.0
        matched: List[str] = []
        missing: List[str] = []
        for wish in wish_products:
            ratio, label = _best_phrase_match(wish, phrases)
            if ratio >= 0.85:
                score += 1.0
                matched.append(label or wish)
            elif ratio >= 0.65:
                score += 0.5
                matched.append(label or wish)
            else:
                missing.append(wish)
        recommendations.append(
            {
                "room": room,
                "score": round(score, 3),
                "matched": matched,
                "missing": missing,
            }
        )

    recommendations.sort(key=lambda entry: (-entry["score"], entry["room"]))
    return recommendations[:5]


def _best_phrase_match(needle: str, phrases: Dict[str, str]) -> Tuple[float, Optional[str]]:
    if not needle:
        return 0.0, None
    target = _normalise_phrase(needle)
    if not target:
        return 0.0, None
    best_ratio = 0.0
    best_label: Optional[str] = None
    for variant, label in phrases.items():
        if not variant:
            continue
        if target == variant:
            return 1.0, label
        if target in variant or variant in target:
            ratio = 0.92
        else:
            ratio = difflib.SequenceMatcher(a=target, b=variant).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_label = label
    return best_ratio, best_label


def _normalise_phrase(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


@lru_cache(maxsize=1)
def _room_catalog() -> Dict[str, Dict[str, Any]]:
    rooms = _load_rooms()
    room_products = {room["name"]: {"phrases": {}, "features": room.get("features") or []} for room in rooms}
    room_ids = {room.get("id", "").strip().lower(): room["name"] for room in rooms if room.get("id")}
    room_aliases = {room["name"].strip().lower(): room["name"] for room in rooms}
    product_records = list_product_records()

    for record in product_records:
        variants = [record.name] + [syn for syn in record.synonyms if syn]
        variants = [variant for variant in variants if variant]
        base_tokens = set()
        for variant in variants:
            base_tokens.update(_tokenize(variant))
        if record.category:
            base_tokens.update(_tokenize(record.category))

        unavailable = {
            room_ids.get(str(room_id).strip().lower())
            or room_aliases.get(str(room_id).strip().lower())
            for room_id in record.unavailable_in
        }
        available_rooms = [room for room in room_products if room not in unavailable]

        for room in available_rooms:
            phrases = room_products[room]["phrases"]
            for variant in variants:
                normalized = _normalise_phrase(variant)
                if normalized:
                    phrases.setdefault(normalized, record.name)
            for token in base_tokens:
                if len(token) >= 3:
                    phrases.setdefault(token, record.name)

    return room_products


@lru_cache(maxsize=1)
def _load_rooms() -> List[Dict[str, Any]]:
    path = Path(__file__).resolve().parents[2] / "rooms.json"
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    rooms = payload.get("rooms")
    if not isinstance(rooms, list):
        return []
    normalised: List[Dict[str, Any]] = []
    for entry in rooms:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not name:
            continue
        normalised.append(entry)
    return normalised


__all__ = ["extract_preferences"]
