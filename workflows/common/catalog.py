from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .capacity import fits_capacity, layout_capacity


def _data_root() -> Path:
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def _rooms_payload() -> Dict[str, Any]:
    path = _data_root() / "data" / "rooms.json"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _room_entries() -> Iterable[Dict[str, Any]]:
    payload = _rooms_payload()
    rooms = payload.get("rooms")
    if isinstance(rooms, list):
        return rooms
    return []


def _catering_payload() -> Dict[str, Any]:
    path = _data_root() / "data" / "products.json"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _normalise_feature(value: str) -> str:
    return value.strip().lower()


def _feature_matches(feature: str, entry: Dict[str, Any]) -> bool:
    target = _normalise_feature(feature)
    if not target:
        return False
    candidates: List[str] = []
    candidates.extend(entry.get("features") or [])
    candidates.extend(entry.get("equipment") or [])
    for raw in candidates:
        if target in _normalise_feature(str(raw)):
            return True
    return False


def _max_capacity(entry: Dict[str, Any]) -> Optional[int]:
    # Support both flat (capacity_max) and nested (capacity.max) formats
    value = entry.get("capacity_max")
    if value is None:
        block = entry.get("capacity") or {}
        value = block.get("max")
    if isinstance(value, (int, float)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    return None


def list_rooms_by_feature(
    feature: str,
    min_capacity: Optional[int] = None,
    layout: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return rooms that expose the requested feature and capacity bounds."""

    matches: List[Dict[str, Any]] = []
    for entry in _room_entries():
        name = entry.get("name")
        if not name or not _feature_matches(feature, entry):
            continue
        max_cap = _max_capacity(entry)
        if min_capacity is not None and max_cap is not None and max_cap < int(min_capacity):
            continue
        if min_capacity is not None and not fits_capacity(name, min_capacity, layout):
            continue
        layout_cap = layout_capacity(name, layout)
        matches.append(
            {
                "name": name,
                "max_capacity": max_cap,
                "layout_capacity": layout_cap,
                "features": list(entry.get("features") or []),
                "equipment": list(entry.get("equipment") or []),
            }
        )
    matches.sort(key=lambda item: (item["max_capacity"] or 0, item["name"]))
    return matches


def list_room_features(room_id: str) -> List[str]:
    """Expose features and equipment for a given room."""

    for entry in _room_entries():
        if str(entry.get("name")).strip().lower() == str(room_id).strip().lower():
            features = list(entry.get("features") or [])
            equipment = list(entry.get("equipment") or [])
            combined = features + equipment
            seen = set()
            ordered: List[str] = []
            for item in combined:
                key = item.strip()
                if key and key not in seen:
                    seen.add(key)
                    ordered.append(key)
            return ordered
    return []


def list_common_room_features(max_features: int = 4) -> List[str]:
    """Return features that are common across all rooms (or most rooms).

    Prioritizes features that appear in ALL rooms, then falls back to
    features in the majority of rooms.

    Args:
        max_features: Maximum number of features to return (default 4)

    Returns:
        List of common feature names, ordered by popularity
    """
    entries = list(_room_entries())
    if not entries:
        return []

    # Count feature occurrences across all rooms
    feature_counts: Dict[str, int] = {}
    for entry in entries:
        features = list(entry.get("features") or [])
        equipment = list(entry.get("equipment") or [])
        combined = set(features + equipment)
        for feat in combined:
            key = feat.strip()
            if key:
                feature_counts[key] = feature_counts.get(key, 0) + 1

    if not feature_counts:
        return []

    total_rooms = len(entries)
    # Sort by count (descending), then alphabetically
    sorted_features = sorted(
        feature_counts.items(),
        key=lambda x: (-x[1], x[0].lower())
    )

    # Return features that appear in at least half the rooms
    min_count = max(1, total_rooms // 2)
    common = [feat for feat, count in sorted_features if count >= min_count]

    return common[:max_features]


# Database-backed product catalog accessor - see config_store.py for defaults
from workflows.io.config_store import get_product_room_map


def _get_product_catalog() -> List[Dict[str, Any]]:
    """Load product catalog from database config (with fallback defaults)."""
    return get_product_room_map()


# Legacy constant - now loads from database config
# Kept for backward compatibility but prefer using _get_product_catalog() for fresh data
_PRODUCT_CATALOG: List[Dict[str, Any]] = _get_product_catalog()


def list_products(
    room_id: Optional[str] = None,
    categories: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    """Return add-on products optionally scoped to a room or category."""

    category_filter = {str(cat).strip().lower() for cat in categories or [] if str(cat).strip()}
    room_norm = str(room_id).strip().lower() if room_id else None
    items: List[Dict[str, Any]] = []
    for entry in _PRODUCT_CATALOG:
        entry_rooms = entry.get("rooms") or []
        if room_norm:
            normed = {str(r).strip().lower() for r in entry_rooms}
            if room_norm not in normed:
                continue
        if category_filter:
            if str(entry.get("category", "")).strip().lower() not in category_filter:
                continue
        items.append(
            {
                "name": entry["name"],
                "category": entry.get("category"),
            }
        )
    items.sort(key=lambda item: (item.get("category") or "", item["name"]))
    return items


def list_catering(
    room_id: Optional[str] = None,
    date_token: Optional[str] = None,
    categories: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Return catering options from products.json.

    The products.json has a flat 'products' array with category field.
    Catering-related categories: "Catering", "Beverages", "Add-ons"

    Args:
        room_id: Optional room to check availability (currently unused)
        date_token: Optional date to check availability (currently unused)
        categories: Optional filter - "package" maps to "Catering",
                   "beverages" maps to "Beverages", etc.
    """
    # Map filter categories to actual product categories
    category_map = {
        "package": "Catering",
        "catering": "Catering",
        "beverages": "Beverages",
        "beverage": "Beverages",
        "add-on": "Add-ons",
        "addon": "Add-ons",
    }

    category_filter = {str(cat).strip().lower() for cat in categories or [] if str(cat).strip()}
    # Convert filter to actual categories
    actual_categories = set()
    for cat in category_filter:
        if cat in category_map:
            actual_categories.add(category_map[cat])

    # If no filter or unrecognized filter, show all catering-related
    if not actual_categories:
        actual_categories = {"Catering", "Beverages", "Add-ons"}

    payload = _catering_payload()
    products = payload.get("products") or []
    results: List[Dict[str, Any]] = []

    for product in products:
        prod_category = product.get("category", "")
        if prod_category not in actual_categories:
            continue

        # Check room availability
        unavailable_in = product.get("unavailable_in") or []
        if room_id and room_id in unavailable_in:
            continue

        entry = {
            "name": product.get("name"),
            "category": prod_category.lower(),
            "price_per_person": product.get("unit_price") if product.get("unit") == "per_person" else None,
            "price": product.get("unit_price"),
            "description": product.get("description"),
        }
        results.append(entry)

    results.sort(key=lambda item: (item.get("category") or "", item.get("name") or ""))
    return results


def _resolve_anchor_date(
    anchor_month: Optional[int],
    anchor_day: Optional[int],
    force_next_year: bool = False,
) -> date:
    """
    Resolve a month/day into a concrete date.

    If force_next_year is True (e.g., "February next year"), always use current_year + 1.
    Otherwise, use current year unless the month has already passed.
    """
    today = date.today()
    if not anchor_month:
        return today
    year = today.year
    if force_next_year:
        # Explicit "next year" mentioned - always add 1
        year += 1
    elif anchor_month < today.month or (anchor_month == today.month and anchor_day and anchor_day < today.day):
        # Month already passed this year - use next year
        year += 1
    safe_day = max(1, min(anchor_day or 1, 28))
    return date(year, anchor_month, safe_day)


def list_free_dates(
    anchor_month: Optional[int] = None,
    anchor_day: Optional[int] = None,
    count: int = 5,
    *,
    db: Optional[Dict[str, Any]] = None,
    preferred_room: Optional[str] = None,
    force_next_year: bool = False,
) -> List[str]:
    """
    Produce deterministic candidate dates.

    When a database is provided we reuse the workflow `suggest_dates` helper to ensure
    availability-aware results. Otherwise we fall back to evenly spaced weekly slots.

    Args:
        force_next_year: If True, the anchor date is always resolved to next year
                         (e.g., "February next year" explicitly mentioned).
    """

    if count <= 0:
        return []

    start_date = _resolve_anchor_date(anchor_month, anchor_day, force_next_year)
    preferred = preferred_room or "Room A"
    if db is not None:
        try:
            from workflows.steps.step1_intake.condition.checks import suggest_dates
        except Exception:
            suggest_dates = None  # type: ignore
        if suggest_dates is not None:
            start_iso = datetime.combine(start_date, datetime.min.time()).isoformat() + "Z"
            candidates = suggest_dates(
                db,
                preferred_room=preferred,
                start_from_iso=start_iso,
                days_ahead=60,
                max_results=count,
            )
            if candidates:
                return candidates[:count]

    # Fallback: weekly cadence anchored to requested month/day.
    results: List[str] = []
    cursor = start_date
    if cursor <= date.today():
        cursor = date.today() + timedelta(days=7)
    while len(results) < count:
        results.append(cursor.strftime("%d.%m.%Y"))
        cursor += timedelta(days=7)
    return results


__all__ = [
    "list_rooms_by_feature",
    "list_room_features",
    "list_common_room_features",
    "list_products",
    "list_catering",
    "list_free_dates",
]
