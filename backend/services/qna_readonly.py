from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Sequence

from backend.services.rooms import RoomRecord, load_room_catalog
from backend.workflows.common.catalog import list_products, list_room_features


@dataclass(frozen=True)
class RoomAvailabilityRow:
    room_id: str
    room_name: str
    capacity_max: Optional[int]
    date: Optional[str]
    status: str
    features: List[str]
    products: List[str]


@dataclass(frozen=True)
class RoomSummary:
    room_id: str
    room_name: str
    capacity_max: Optional[int]
    capacity_by_layout: Dict[str, int]
    products: List[str]


@dataclass(frozen=True)
class ProductRecord:
    product: str
    category: Optional[str]
    rooms: List[str]
    available_today: bool
    attributes: List[str]


def fetch_room_availability(
    *,
    date_scope: Any,
    attendee_scope: Any,
    room_filter: Optional[str],
    exclude_rooms: Sequence[str],
    product_requirements: Sequence[str],
) -> List[RoomAvailabilityRow]:
    """Read-only availability listing tailored by the structured context."""

    catalogue = _catalog()
    exclude_normalised = {room.lower() for room in exclude_rooms}
    requested_room = room_filter.lower() if isinstance(room_filter, str) else None
    min_capacity = _attendee_min(attendee_scope)

    rows: List[RoomAvailabilityRow] = []
    for record in catalogue:
        if requested_room and not record.matches_identifier(requested_room):
            continue
        if record.name.lower() in exclude_normalised:
            continue
        if min_capacity is not None and record.capacity_max is not None and record.capacity_max < min_capacity:
            continue
        if product_requirements and not _room_supports_products(record.name, product_requirements):
            continue
        rows.append(
            RoomAvailabilityRow(
                room_id=record.room_id,
                room_name=record.name,
                capacity_max=record.capacity_max,
                date=_primary_date_label(date_scope),
                status="available",
                features=list(record.features),
                products=list(product_requirements),
            )
        )
    return rows


def list_rooms_by_capacity(
    *,
    min_capacity: Optional[int],
    capacity_range: Optional[Dict[str, int]],
    product_requirements: Sequence[str],
) -> List[RoomSummary]:
    """Read-only room catalog selection constrained by capacity and products."""

    catalogue = _catalog()
    rows: List[RoomSummary] = []
    min_cap = min_capacity
    if capacity_range and capacity_range.get("min") is not None:
        if min_cap is None or capacity_range["min"] > min_cap:
            min_cap = capacity_range["min"]
    for record in catalogue:
        max_cap = record.capacity_max
        if min_cap is not None and max_cap is not None and max_cap < min_cap:
            continue
        if product_requirements and not _room_supports_products(record.name, product_requirements):
            continue
        rows.append(
            RoomSummary(
                room_id=record.room_id,
                room_name=record.name,
                capacity_max=max_cap,
                capacity_by_layout=dict(record.capacity_by_layout),
                products=list(product_requirements),
            )
        )
    return rows


def fetch_product_repertoire(
    *,
    product_names: Sequence[str],
    effective_date: date,
    room_filter: Optional[str],
) -> List[ProductRecord]:
    """Read-only snapshot of product repertoire for the requested scope."""

    room_normalised = room_filter.lower() if isinstance(room_filter, str) else None
    products = list_products(room_id=room_filter)

    filtered: List[ProductRecord] = []
    requested = {name.lower() for name in product_names} if product_names else set()

    for entry in products:
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        category = entry.get("category")
        rooms = entry.get("rooms") if isinstance(entry.get("rooms"), list) else []
        if room_normalised:
            canonical_rooms = {str(room).strip().lower() for room in rooms}
            if canonical_rooms and room_normalised not in canonical_rooms:
                continue
        if requested and name.lower() not in requested:
            continue
        filtered.append(
            ProductRecord(
                product=name,
                category=str(category) if category else None,
                rooms=list(rooms),
                available_today=True,
                attributes=[],
            )
        )

    if not product_names:
        return filtered

    existing = {record.product.lower() for record in filtered}
    for name in product_names:
        if name.lower() in existing:
            continue
        filtered.append(
            ProductRecord(
                product=name,
                category=None,
                rooms=[],
                available_today=False,
                attributes=[],
            )
        )
    return filtered


def load_room_static(room_id: str) -> Dict[str, Any]:
    """Return static room metadata (capacity span, features, descriptive fields)."""

    if not room_id:
        return {}

    record = _catalog_lookup(room_id)
    features = list_room_features(room_id)
    summary: Dict[str, Any] = {
        "room_id": room_id,
        "room_name": record.name if record else room_id,
        "capacity_max": record.capacity_max if record else None,
        "capacity_by_layout": dict(record.capacity_by_layout) if record else {},
        "features": features,
    }
    info = _room_info_lookup().get(room_id.lower())
    if info:
        summary.update(
            {
                "size_sqm": info.get("size_sqm"),
                "best_for": info.get("best_for"),
                "capacity_span": info.get("capacity"),
            }
        )
    return summary


@lru_cache(maxsize=1)
def _catalog() -> List[RoomRecord]:
    return list(load_room_catalog())


def _catalog_lookup(room_id: str) -> Optional[RoomRecord]:
    room_norm = room_id.lower()
    for record in _catalog():
        if record.matches_identifier(room_norm):
            return record
    return None


def _room_supports_products(room_name: str, products: Sequence[str]) -> bool:
    if not products:
        return True
    available = list_products(room_id=room_name)
    available_names = {str(entry.get("name") or "").strip().lower() for entry in available}
    for product in products:
        if product.lower() not in available_names:
            return False
    return True


def _primary_date_label(scope: Any) -> Optional[str]:
    if isinstance(scope, str):
        return scope
    if isinstance(scope, dict):
        if "start" in scope:
            return scope["start"]
        if "date" in scope:
            return scope["date"]
    return None


def _attendee_min(scope: Any) -> Optional[int]:
    if isinstance(scope, int):
        return scope
    if isinstance(scope, dict):
        minimum = scope.get("min") or scope.get("minimum")
        if minimum is not None:
            try:
                return int(minimum)
            except (TypeError, ValueError):
                return None
        maximum = scope.get("max") or scope.get("maximum")
        if maximum is not None:
            try:
                return int(maximum)
            except (TypeError, ValueError):
                return None
    return None


@lru_cache(maxsize=1)
def _room_info_lookup() -> Dict[str, Dict[str, Any]]:
    from pathlib import Path
    import json

    data_path = Path(__file__).resolve().parents[1] / "room_info.json"
    if not data_path.exists():
        return {}
    with data_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    rooms = payload.get("rooms") if isinstance(payload, dict) else []
    lookup: Dict[str, Dict[str, Any]] = {}
    for entry in rooms or []:
        name = str(entry.get("name") or "").strip()
        if name:
            lookup[name.lower()] = entry
    return lookup


__all__ = [
    "fetch_room_availability",
    "list_rooms_by_capacity",
    "fetch_product_repertoire",
    "load_room_static",
    "RoomAvailabilityRow",
    "RoomSummary",
    "ProductRecord",
]
