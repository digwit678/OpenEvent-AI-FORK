from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from utils import json_io


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
    catalog_path = path or Path(__file__).resolve().parents[1] / "data" / "products.json"
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

        unit = raw.get("unit")
        if unit:
            item["unit"] = unit
        if raw.get("category"):
            item["category"] = raw.get("category")
        if raw.get("wish"):
            item["wish"] = raw.get("wish")

        qty = raw.get("quantity")
        if qty is not None:
            try:
                item["quantity"] = max(1, int(qty))
            except (TypeError, ValueError):
                pass
        elif record and record.unit == "per_person" and participant_count:
            item["quantity"] = participant_count
        elif item.get("unit") == "per_person" and participant_count:
            # Custom payload with explicit per-person unit
            item["quantity"] = participant_count
        else:
            # Default to a single unit so downstream math does not explode quantities
            item["quantity"] = item.get("quantity", 1)

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


# =============================================================================
# Category-based semantic matching
# =============================================================================

@lru_cache(maxsize=1)
def _build_category_keywords() -> Dict[str, set]:
    """
    Build a mapping of category -> set of keywords (names + synonyms).
    Loaded once and cached for performance.
    """
    catalog = _load_catalog()
    category_keywords: Dict[str, set] = {}

    for record in catalog.values():
        category = (record.category or "").strip()
        if not category:
            continue

        if category not in category_keywords:
            category_keywords[category] = set()

        # Add product name (lowercase, split into words)
        name_lower = record.name.lower()
        category_keywords[category].add(name_lower)
        for word in name_lower.split():
            if len(word) > 2:  # Skip very short words
                category_keywords[category].add(word)

        # Add all synonyms
        for synonym in record.synonyms:
            category_keywords[category].add(synonym.lower())
            for word in synonym.lower().split():
                if len(word) > 2:
                    category_keywords[category].add(word)

    return category_keywords


def get_categories() -> List[str]:
    """Get all unique product categories from the catalog."""
    return list(_build_category_keywords().keys())


def text_matches_category(text: str, category: str) -> bool:
    """
    Check if the given text semantically matches the specified category.
    Uses product names and synonyms from the catalog for matching.

    Args:
        text: User text to check (will be lowercased)
        category: Category name (e.g., "Catering", "Equipment")

    Returns:
        True if any category keyword is found in the text
    """
    if not text or not category:
        return False

    keywords = _build_category_keywords().get(category, set())
    if not keywords:
        return False

    text_lower = text.lower()

    # Exclude common false positives where event/room descriptions contain category keywords
    # E.g., "conference room" should NOT match Equipment category due to "conference" keyword
    # (conference camera is equipment, but conference room is not)
    # Similarly, "dinner party" is an event type, not a catering product request
    false_positive_phrases = [
        # Equipment false positives (room types)
        "conference room",
        "video room",
        "presentation room",
        "screen room",
        # Catering false positives (event types - not actual catering requests)
        "dinner party",
        "dinner event",
        "lunch meeting",
        "lunch event",
        "breakfast meeting",
        "cocktail party",
        "cocktail event",
        "cocktail reception",
    ]
    text_cleaned = text_lower
    for phrase in false_positive_phrases:
        text_cleaned = text_cleaned.replace(phrase, " ")

    return any(kw in text_cleaned for kw in keywords)


def detect_mentioned_categories(text: str) -> List[str]:
    """
    Detect which product categories are mentioned in the text.

    Args:
        text: User text to analyze

    Returns:
        List of category names that have matches in the text
    """
    if not text:
        return []

    mentioned = []
    for category in get_categories():
        if text_matches_category(text, category):
            mentioned.append(category)
    return mentioned


def has_specific_product_request(text: str, exclude_categories: Optional[List[str]] = None) -> bool:
    """
    Check if user mentioned specific products from categories OTHER than the excluded ones.

    Useful for checking if user asked for equipment/add-ons without mentioning catering.

    Args:
        text: User text to analyze
        exclude_categories: Categories to ignore (e.g., ["Catering", "Beverages"])

    Returns:
        True if user mentioned products from non-excluded categories
    """
    if not text:
        return False

    exclude = set(c.lower() for c in (exclude_categories or []))
    mentioned = detect_mentioned_categories(text)

    for cat in mentioned:
        if cat.lower() not in exclude:
            return True
    return False


# =============================================================================
# Product Availability Filtering (Three-Tier System)
# =============================================================================
#
# Three-tier product availability:
#   - RECOMMENDED: AI suggests in offers & answers questions (default)
#   - ON_REQUEST: Not suggested by AI, but manager can add manually
#   - UNAVAILABLE: Completely hidden, cannot be added even manually
#
# Functions:
#   - list_recommended_products(): Only 'recommended' products (for AI suggestions)
#   - list_available_products(): 'recommended' + 'on_request' (for manual addition)
#   - is_product_recommended(): Check if AI should suggest this product
#   - is_product_available(): Check if product can be added to offers
# =============================================================================

def list_recommended_products(path: Optional[Path] = None) -> List[ProductRecord]:
    """
    Return only RECOMMENDED products from the catalog.

    Filters out both 'on_request' and 'unavailable' products.
    USE THIS FOR AI SUGGESTIONS - the AI should only recommend these products.

    This function is NOT cached because the status lists can change at runtime.

    Args:
        path: Optional path to products.json (for testing)

    Returns:
        List of ProductRecord for recommended products only
    """
    from workflows.io.config_store import is_product_recommended

    all_products = list_product_records(path)
    return [p for p in all_products if is_product_recommended(p.product_id)]


def list_available_products(path: Optional[Path] = None) -> List[ProductRecord]:
    """
    Return products that CAN be added to offers (recommended + on_request).

    Filters out only 'unavailable' products.
    Use this for manual product addition by managers.

    For AI suggestions, use list_recommended_products() instead.

    Args:
        path: Optional path to products.json (for testing)

    Returns:
        List of ProductRecord for available products (recommended + on_request)
    """
    from workflows.io.config_store import is_product_enabled

    all_products = list_product_records(path)
    return [p for p in all_products if is_product_enabled(p.product_id)]


def is_product_recommended(product_id: str) -> bool:
    """
    Check if a product should be RECOMMENDED by AI.

    Returns True only for 'recommended' status products.
    Returns False for 'on_request' and 'unavailable' products.

    Args:
        product_id: The product ID to check

    Returns:
        True if the product should be suggested by AI
    """
    from workflows.io.config_store import is_product_recommended as config_is_recommended

    if not product_id:
        return False

    # First check if product exists in catalog
    catalog = _load_catalog()
    product_exists = any(p.product_id == product_id for p in catalog.values())

    if not product_exists:
        return False

    return config_is_recommended(product_id)


def is_product_available(product_id: str) -> bool:
    """
    Check if a product CAN be added to offers (by manager).

    Returns True for 'recommended' and 'on_request' products.
    Returns False only for 'unavailable' products.

    Args:
        product_id: The product ID to check

    Returns:
        True if the product can be added to offers
    """
    from workflows.io.config_store import is_product_enabled

    if not product_id:
        return False

    # First check if product exists in catalog
    catalog = _load_catalog()
    product_exists = any(p.product_id == product_id for p in catalog.values())

    if not product_exists:
        return False

    return is_product_enabled(product_id)


def find_available_product(name: str) -> Optional[ProductRecord]:
    """
    Find a product by name, but only if it's available (not unavailable).

    Like find_product(), but returns None if the product is unavailable.
    Returns the product even if it's 'on_request' (can be added manually).

    Args:
        name: Product name to search for

    Returns:
        ProductRecord if found and available, None otherwise
    """
    from workflows.io.config_store import is_product_enabled

    record = find_product(name)
    if record is None:
        return None

    if not is_product_enabled(record.product_id):
        return None

    return record


def find_recommended_product(name: str) -> Optional[ProductRecord]:
    """
    Find a product by name, but only if it's recommended (for AI use).

    Like find_product(), but returns None if the product is on_request or unavailable.

    Args:
        name: Product name to search for

    Returns:
        ProductRecord if found and recommended, None otherwise
    """
    from workflows.io.config_store import is_product_recommended as config_is_recommended

    record = find_product(name)
    if record is None:
        return None

    if not config_is_recommended(record.product_id):
        return None

    return record
