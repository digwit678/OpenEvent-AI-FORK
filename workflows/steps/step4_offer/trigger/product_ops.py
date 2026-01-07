"""
Product operations utilities for Step4 offer workflow.

Extracted from step4_handler.py for better modularity (O1 refactoring).
These functions handle product add/remove operations, autofill from preferences,
and product normalization during offer preparation.

Usage:
    from workflows.steps.step4_offer.trigger.product_ops import (
        apply_product_operations,
        autofill_products_from_preferences,
    )

    changes = apply_product_operations(event_entry, user_info)
    if changes:
        state.extras["persist"] = True
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, List, Optional, Set

from services.products import find_product, normalise_product_payload
from services.rooms import load_room_catalog
from workflows.common.menu_options import DINNER_MENU_OPTIONS


# -----------------------------------------------------------------------------
# Pure helper functions (no state modification)
# -----------------------------------------------------------------------------


def products_ready(event_entry: Dict[str, Any]) -> bool:
    """Check if products are ready (list non-empty, sourced, or skip flag set)."""
    products = event_entry.get("products") or []
    selected = event_entry.get("selected_products") or []
    products_state = event_entry.get("products_state") or {}
    line_items = products_state.get("line_items") or []
    skip_flag = bool(products_state.get("skip_products") or event_entry.get("products_skipped"))
    # Sourced products (from HIL sourcing flow) count as ready
    sourced = event_entry.get("sourced_products") or {}
    return bool(products or selected or line_items or skip_flag or sourced)


def ensure_products_container(event_entry: Dict[str, Any]) -> None:
    """Ensure products list exists in event_entry."""
    if "products" not in event_entry or not isinstance(event_entry["products"], list):
        event_entry["products"] = []


def has_offer_update(user_info: Dict[str, Any]) -> bool:
    """Check if user_info contains any product/offer update keys."""
    update_keys = (
        "products_add",
        "products_remove",
        "products_skip",
        "skip_products",
        "products_none",
        "offer_total_override",
        "room_rate",
        "offer_id",
    )
    return any(bool(user_info.get(key)) for key in update_keys)


def menu_name_set() -> Set[str]:
    """Return set of dinner menu names (lowercase)."""
    return {
        str(entry.get("menu_name") or "").strip().lower()
        for entry in DINNER_MENU_OPTIONS
        if entry.get("menu_name")
    }


def infer_participant_count(event_entry: Dict[str, Any]) -> Optional[int]:
    """Get participant count from requirements, event_data, or captured."""
    requirements = event_entry.get("requirements") or {}
    participants = requirements.get("number_of_participants")
    if participants is None:
        participants = (event_entry.get("event_data") or {}).get("Number of Participants")
    if participants is None:
        participants = (event_entry.get("captured") or {}).get("participants")
    try:
        return int(str(participants).strip())
    except (TypeError, ValueError, AttributeError):
        return None


# -----------------------------------------------------------------------------
# Room alias utilities
# -----------------------------------------------------------------------------


@lru_cache(maxsize=1)
def room_alias_map() -> Dict[str, Set[str]]:
    """Build cached mapping of room names to their aliases."""
    mapping: Dict[str, Set[str]] = {}
    for record in load_room_catalog():
        identifiers = {
            record.name.strip().lower(),
            (record.room_id or record.name).strip().lower(),
        }
        mapping[record.name] = identifiers
    return mapping


def room_aliases(room_name: str) -> Set[str]:
    """Get all aliases for a room name."""
    lowered = (room_name or "").strip().lower()
    aliases: Set[str] = {lowered}
    for identifiers in room_alias_map().values():
        if lowered in identifiers:
            aliases |= identifiers
            break
    return aliases


def product_unavailable_in_room(record: Any, room_name: str) -> bool:
    """Check if a product is unavailable in the given room."""
    aliases = room_aliases(room_name)
    record_unavailable = {str(entry).strip().lower() for entry in getattr(record, "unavailable_in", [])}
    return any(alias in record_unavailable for alias in aliases)


# -----------------------------------------------------------------------------
# Product normalization utilities
# -----------------------------------------------------------------------------


def normalise_products(payload: Any, *, participant_count: Optional[int] = None) -> List[Dict[str, Any]]:
    """Normalize product payload for adding to products list."""
    return normalise_product_payload(payload, participant_count=participant_count)


def normalise_product_names(payload: Any) -> List[str]:
    """Extract and lowercase product names from payload."""
    if not payload:
        return []
    items = payload if isinstance(payload, list) else [payload]
    names: List[str] = []
    for raw in items:
        if isinstance(raw, dict):
            name = raw.get("name")
        else:
            name = raw
        text = str(name or "").strip()
        if text:
            names.append(text.lower())
    return names


def upsert_product(products: List[Dict[str, Any]], item: Dict[str, Any]) -> None:
    """Add or update product in the products list. For existing products, increments quantity."""
    for existing in products:
        if existing["name"].lower() == item["name"].lower():
            # Increment quantity instead of replacing it
            existing["quantity"] = existing.get("quantity", 0) + item.get("quantity", 1)
            existing["unit_price"] = item["unit_price"]
            return
    products.append(item)


def normalise_product_fields(product: Dict[str, Any], *, menu_names: Optional[Set[str]] = None) -> Dict[str, Any]:
    """Normalize product quantity/unit for pricing and display."""
    menu_names = menu_names or menu_name_set()
    normalised = dict(product)
    name = str(normalised.get("name") or "").strip()
    unit = normalised.get("unit")
    if not unit and name.lower() in menu_names:
        unit = "per_event"
    try:
        quantity = float(normalised.get("quantity") or 1)
    except (TypeError, ValueError):
        quantity = 1
    try:
        unit_price = float(normalised.get("unit_price") or 0.0)
    except (TypeError, ValueError):
        unit_price = 0.0

    if unit == "per_event":
        quantity = 1

    normalised["name"] = name or "Unnamed item"
    normalised["unit"] = unit
    normalised["quantity"] = quantity
    normalised["unit_price"] = unit_price
    return normalised


# -----------------------------------------------------------------------------
# Product line building utilities
# -----------------------------------------------------------------------------


def build_product_line_from_record(record: Any, participants: Optional[int]) -> Dict[str, Any]:
    """Build a product line item dict from a catalog record."""
    quantity = 1
    if record.unit == "per_person" and participants:
        quantity = max(1, int(participants))
    item: Dict[str, Any] = {
        "name": record.name,
        "quantity": quantity,
        "unit_price": float(record.base_price or 0.0),
    }
    if getattr(record, "product_id", None):
        item["product_id"] = record.product_id
    if getattr(record, "unit", None):
        item["unit"] = record.unit
    if getattr(record, "category", None):
        item["category"] = record.category
    return item


def summarize_product_line(
    record: Any,
    wish: Optional[str],
    score: float,
    item: Dict[str, Any],
) -> Dict[str, Any]:
    """Create autofill summary entry for a product line."""
    unit_price = float(item.get("unit_price") or 0.0)
    quantity = int(item.get("quantity") or 1)
    total = unit_price * quantity
    return {
        "name": record.name,
        "category": record.category or "General",
        "unit": record.unit,
        "wish": wish,
        "match_pct": int(round(score * 100)),
        "unit_price": unit_price,
        "quantity": quantity,
        "total": round(total, 2),
    }


def build_alternative_suggestions(
    raw_alternatives: List[Dict[str, Any]],
    included_lower: Set[str],
    room_name: str,
    *,
    min_score: float,
) -> Dict[str, List[Dict[str, Any]]]:
    """Build alternative product suggestions, split by category."""
    best_by_product: Dict[str, Dict[str, Any]] = {}
    for entry in raw_alternatives:
        product_name = entry.get("product")
        if not product_name:
            continue
        score = float(entry.get("score") or 0.0)
        if score < min_score:
            continue
        record = find_product(product_name)
        if not record or product_unavailable_in_room(record, room_name):
            continue
        key = record.name.strip().lower()
        if key in included_lower:
            continue
        stored = best_by_product.get(key)
        if stored and stored["score"] >= score:
            continue
        best_by_product[key] = {
            "name": record.name,
            "category": record.category or "General",
            "unit": record.unit,
            "unit_price": float(record.base_price or 0.0),
            "score": score,
            "wish": entry.get("wish"),
        }

    product_alternatives: List[Dict[str, Any]] = []
    catering_alternatives: List[Dict[str, Any]] = []
    for payload in sorted(best_by_product.values(), key=lambda item: item["score"], reverse=True):
        formatted = {
            "name": payload["name"],
            "category": payload["category"],
            "unit": payload["unit"],
            "unit_price": payload["unit_price"],
            "match_pct": int(round(payload["score"] * 100)),
            "wish": payload.get("wish"),
        }
        category_lower = (payload["category"] or "").strip().lower()
        if category_lower in {"catering", "beverages"}:
            catering_alternatives.append(formatted)
        else:
            product_alternatives.append(formatted)

    return {"products": product_alternatives, "catering": catering_alternatives}


# -----------------------------------------------------------------------------
# Main product operations (state-modifying)
# -----------------------------------------------------------------------------


def apply_product_operations(event_entry: Dict[str, Any], user_info: Dict[str, Any]) -> bool:
    """
    Apply product add/remove/skip operations from user_info to event_entry.

    Handles:
    - products_add: Add products to the list
    - products_remove: Remove products by name
    - skip_products/products_skip/products_none: Set skip flag

    Returns True if any changes were made.
    """
    import logging
    logger = logging.getLogger(__name__)

    # DEBUG: Log what products_add contains
    raw_products_add = user_info.get("products_add")
    if raw_products_add:
        logger.warning("[PRODUCT_DEBUG] apply_product_operations called with products_add: %s (type: %s, len: %s)",
                      raw_products_add[:3] if isinstance(raw_products_add, list) else raw_products_add,
                      type(raw_products_add).__name__,
                      len(raw_products_add) if isinstance(raw_products_add, list) else 1)

    participant_count = infer_participant_count(event_entry)
    additions = normalise_products(
        user_info.get("products_add"),
        participant_count=participant_count,
    )

    # DEBUG: Log normalized additions
    if additions:
        logger.warning("[PRODUCT_DEBUG] Normalized additions (%d items): %s",
                      len(additions), [a.get("name") for a in additions[:5]])
    removals = normalise_product_names(user_info.get("products_remove"))
    changes = False

    if additions:
        for item in additions:
            upsert_product(event_entry["products"], item)
        changes = True

    if removals:
        event_entry["products"] = [item for item in event_entry["products"] if item["name"].lower() not in removals]
        changes = True

    skip_flag = any(bool(user_info.get(key)) for key in ("products_skip", "skip_products", "products_none"))
    if skip_flag:
        products_state = event_entry.setdefault("products_state", {})
        products_state["skip_products"] = True
        changes = True

    if changes:
        products_state = event_entry.setdefault("products_state", {})
        products_state.pop("awaiting_client_products", None)
        summary = products_state.get("autofill_summary")
        if summary is not None:
            # Clear matched entries so the offer summary reflects the explicit product list.
            summary["matched"] = []

    return changes


def autofill_products_from_preferences(
    event_entry: Dict[str, Any],
    user_info: Dict[str, Any],
    *,
    min_score: float = 0.5,
) -> bool:
    """
    Autofill products from preferences if not already done.

    Checks room match breakdown and adds products that meet the min_score threshold.
    Returns True if products were actually added.
    """
    products_state = event_entry.setdefault("products_state", {})
    if products_state.get("autofill_applied"):
        return False

    # Prevent autofill if products were already manually selected or modified.
    if has_offer_update(user_info):
        return False

    existing_products = event_entry.get("products") or []
    if existing_products:
        products_state["autofill_applied"] = True
        return False

    preferences = {}
    event_prefs = event_entry.get("preferences")
    if isinstance(event_prefs, dict):
        preferences = dict(event_prefs)
    elif isinstance(user_info.get("preferences"), dict):
        preferences = dict(user_info["preferences"])
    if not preferences:
        return False

    selected_room = event_entry.get("locked_room_id")
    if not selected_room:
        pending = event_entry.get("room_pending_decision") or {}
        selected_room = pending.get("selected_room")
    if not selected_room:
        return False

    breakdown_map = preferences.get("room_match_breakdown") or {}
    breakdown = breakdown_map.get(selected_room)
    if not isinstance(breakdown, dict):
        return False

    matches_detail = breakdown.get("matches_detail") or []
    matched_names = breakdown.get("matched") or []
    if not matches_detail and matched_names:
        matches_detail = [{"product": name, "wish": None, "score": 1.0} for name in matched_names if name]

    if not matches_detail:
        return False

    participants = infer_participant_count(event_entry)
    match_threshold = max(0.65, min_score)
    additions: List[Dict[str, Any]] = []
    summary_entries: List[Dict[str, Any]] = []
    included_lower: Set[str] = set()

    for entry in matches_detail:
        product_name = entry.get("product")
        if not product_name:
            continue
        score = float(entry.get("score") or 0.0)
        if score < match_threshold:
            continue
        record = find_product(product_name)
        if not record or product_unavailable_in_room(record, selected_room):
            continue
        product_key = record.name.strip().lower()
        if product_key in included_lower:
            continue
        item = build_product_line_from_record(record, participants)
        additions.append(item)
        summary_entries.append(summarize_product_line(record, entry.get("wish"), score, item))
        included_lower.add(product_key)

    if not additions:
        # No confident matches; keep prompt logic in place.
        return False

    for item in additions:
        upsert_product(event_entry["products"], item)

    alternatives_payload = build_alternative_suggestions(
        breakdown.get("alternatives") or [],
        included_lower,
        selected_room,
        min_score=min_score,
    )

    products_state["autofill_summary"] = {
        "matched": summary_entries,
        "alternatives": alternatives_payload["products"],
        "catering_alternatives": alternatives_payload["catering"],
    }
    products_state["autofill_applied"] = True
    return True


__all__ = [
    # Core operations
    "apply_product_operations",
    "autofill_products_from_preferences",
    # State checks
    "products_ready",
    "ensure_products_container",
    "has_offer_update",
    # Participant count
    "infer_participant_count",
    # Room utilities
    "room_alias_map",
    "room_aliases",
    "product_unavailable_in_room",
    # Normalization
    "normalise_products",
    "normalise_product_names",
    "normalise_product_fields",
    "upsert_product",
    # Menu
    "menu_name_set",
    # Line building
    "build_product_line_from_record",
    "summarize_product_line",
    "build_alternative_suggestions",
]
