from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from backend.utils import json_io


@dataclass
class ProductRecord:
    product_id: str
    name: str
    category: Optional[str]
    unit: Optional[str]
    base_price: float
    unavailable_in: List[str]
    synonyms: List[str] = field(default_factory=list)


@lru_cache(maxsize=1)
def _load_catalog(path: Optional[Path] = None) -> Dict[str, ProductRecord]:
    catalog_path = path or Path(__file__).resolve().parents[1] / "data" / "catalog" / "catering.json"
    if not catalog_path.exists():
        return {}
    with catalog_path.open("r", encoding="utf-8") as handle:
        payload = json_io.load(handle)
    items = payload.get("products") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return {}
    records: Dict[str, ProductRecord] = {}
    for entry in items:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        product_id = str(entry.get("id") or name).strip()
        if not name:
            continue
        unavailable_in = [str(item).strip().lower() for item in entry.get("unavailable_in", [])]
        try:
            price = float(entry.get("unit_price") or 0.0)
        except (TypeError, ValueError):
            price = 0.0
        synonyms = [str(item).strip().lower() for item in entry.get("synonyms", []) if str(item).strip()]
        records[name.lower()] = ProductRecord(
            product_id=product_id or name,
            name=name,
            category=entry.get("category"),
            unit=entry.get("unit"),
            base_price=price,
            unavailable_in=unavailable_in,
            synonyms=synonyms,
        )
    return records


def list_product_records(path: Optional[Path] = None) -> List[ProductRecord]:
    """Expose the full product catalog as ProductRecord entries."""

    return list(_load_catalog(path).values())


def find_product(name: str) -> Optional[ProductRecord]:
    if not name:
        return None
    catalog = _load_catalog()
    record = catalog.get(name.strip().lower())
    if record:
        return record
    # Attempt fuzzy lookup using synonyms
    lowered = name.strip().lower()
    for entry in catalog.values():
        if lowered in entry.synonyms:
            return entry
    return None


def _copy_product_record(record: ProductRecord, quantity: Optional[int] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"name": record.name}
    if quantity is None:
        quantity = 1
    payload["quantity"] = quantity
    if record.base_price:
        payload["unit_price"] = record.base_price
    if record.unit:
        payload["unit"] = record.unit
    payload["product_id"] = record.product_id
    if record.category:
        payload["category"] = record.category
    return payload


def normalise_product_payload(
    payload: Any, *, participant_count: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Canonicalise user-provided product selections into a deterministic list.
    Participant count is used to pre-fill per-person quantities where sensible.
    """

    if not payload:
        return []

    items = payload if isinstance(payload, list) else [payload]
    normalised: List[Dict[str, Any]] = []
    seen: Dict[str, Dict[str, Any]] = {}

    for raw in items:
        if isinstance(raw, str):
            name = raw.strip()
            if not name:
                continue
            record = find_product(name)
            if record:
                quantity = participant_count if record.unit == "per_person" and participant_count else None
                item = _copy_product_record(record, quantity)
            else:
                item = {"name": name}
            seen.setdefault(item["name"].lower(), item)
            continue

        if not isinstance(raw, dict):
            continue

        name = str(raw.get("name") or "").strip()
        if not name:
            continue

        record = find_product(name)
        if record:
            item = _copy_product_record(record)
        else:
            item = {"name": name}

        qty = raw.get("quantity")
        if qty is not None:
            try:
                item["quantity"] = max(1, int(qty))
            except (TypeError, ValueError):
                pass
        elif record and record.unit == "per_person" and participant_count:
            item["quantity"] = participant_count

        price = raw.get("unit_price")
        if price is not None:
            try:
                item["unit_price"] = float(price)
            except (TypeError, ValueError):
                pass

        seen.setdefault(item["name"].lower(), item)

    normalised.extend(seen.values())
    return normalised


def merge_product_requests(
    existing: Optional[Sequence[Dict[str, Any]]], incoming: Sequence[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Merge requested products, deduplicating by lowercase name while preserving existing entries.
    """

    existing_list = list(existing or [])
    index = {str(item.get("name") or "").strip().lower(): dict(item) for item in existing_list if item.get("name")}

    updated = False
    for item in incoming:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in index:
            target = index[key]
            quantity = item.get("quantity")
            if quantity is not None and target.get("quantity") != quantity:
                target["quantity"] = quantity
                updated = True
            price = item.get("unit_price")
            if price is not None and target.get("unit_price") != price:
                target["unit_price"] = price
                updated = True
            continue
        index[key] = dict(item)
        updated = True

    if not updated:
        return existing_list

    return list(index.values())


def check_availability(
    selected_products: List[Dict[str, Any]],
    room_identifier: Optional[str],
    event_date_iso: Optional[str],
) -> Dict[str, List[Dict[str, Any]]]:
    catalog = _load_catalog()
    room_key = (room_identifier or "").strip().lower()

    available: List[Dict[str, Any]] = []
    missing: List[Dict[str, Any]] = []

    for item in selected_products or []:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        quantity = item.get("quantity", 1)
        record = catalog.get(name.lower())
        if not record:
            missing.append({"name": name, "reason": "Not part of the standard catalogue."})
            continue
        if room_key and room_key in record.unavailable_in:
            missing.append({"name": name, "reason": f"Not available in {room_identifier}."})
            continue
        available.append(
            {
                "name": record.name,
                "quantity": quantity,
                "unit": record.unit,
                "unit_price": record.base_price,
                "product_id": record.product_id,
                "category": record.category,
            }
        )

    return {"available": available, "missing": missing}
