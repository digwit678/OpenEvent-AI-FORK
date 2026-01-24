"""
Step 1 Product Detection Functions.

I1 Phase 2: Product detection helpers for intake processing.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from workflows.common.menu_options import DINNER_MENU_OPTIONS
from services.products import list_product_records, merge_product_requests, normalise_product_payload

from .keyword_matching import (
    PRODUCT_ADD_KEYWORDS,
    PRODUCT_REMOVE_KEYWORDS,
    contains_keyword,
    match_product_token,
    extract_quantity_from_window,
    menu_token_candidates,
)
from .entity_extraction import participants_from_event


# Generic tokens to skip when matching last word of product names
_GENERIC_PRODUCT_TOKENS = frozenset([
    "menu", "option", "service", "package", "setup", "equipment",
    "rental", "fee", "charge", "cost", "price", "room", "space",
])


def menu_price_value(price: Any) -> Optional[float]:
    """Extract numeric price value from various formats.

    Args:
        price: Price value (can be int, float, or string like "CHF 85")

    Returns:
        Float price value or None
    """
    if price is None:
        return None
    if isinstance(price, (int, float)):
        return float(price)
    try:
        # Handle strings like "CHF 85" or "85.00"
        price_str = str(price).replace("CHF", "").replace("$", "").strip()
        return float(price_str)
    except (TypeError, ValueError):
        return None


def detect_menu_choice(text: str) -> Optional[Dict[str, Any]]:
    """Detect explicit menu selection from message text.

    Matches known menu names from DINNER_MENU_OPTIONS.

    Args:
        text: Message text to analyze

    Returns:
        Dict with menu details if found, None otherwise
    """
    if not text:
        return None

    text_lower = text.lower()

    for menu in DINNER_MENU_OPTIONS:
        name = str(menu.get("menu_name") or "").strip()
        if not name:
            continue

        # Match menu name (case-insensitive, word boundary)
        pattern = rf"\b{re.escape(name.lower())}\b"
        if re.search(pattern, text_lower):
            return {
                "name": name,
                "price": menu_price_value(menu.get("price")),
                "unit": menu.get("unit") or "per_event",
            }

        # Also try matching without "Menu" suffix
        if name.lower().endswith(" menu"):
            short_name = name[:-5].strip()
            pattern = rf"\b{re.escape(short_name.lower())}\b"
            if re.search(pattern, text_lower):
                return {
                    "name": name,
                    "price": menu_price_value(menu.get("price")),
                    "unit": menu.get("unit") or "per_event",
                }

    return None


def detect_bulk_menu_removal(text: str) -> bool:
    """Detect if user wants to remove all menus/food.

    Matches patterns like:
    - "remove all menus"
    - "no food"
    - "don't need any food"
    - "cancel catering"

    Args:
        text: Lowercase message text

    Returns:
        True if bulk menu removal detected
    """
    bulk_patterns = [
        r"\b(remove|cancel|delete)\b.*\b(all|every)\b.*\b(menu|food|catering)\b",
        r"\bno\s+(food|catering|menus?)\b",
        r"\b(don'?t|do\s+not)\s+(need|want)\b.*\b(food|catering|menus?)\b",
        r"\b(cancel|remove)\b.*\b(catering|food)\b",
    ]
    for pattern in bulk_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def detect_product_update_request(
    message_payload: Dict[str, Any],
    user_info: Dict[str, Any],
    linked_event: Optional[Dict[str, Any]],
) -> bool:
    """Detect product additions or removals in message.

    Scans the message for product keywords and determines if user
    is requesting to add or remove products.

    Args:
        message_payload: Raw message data
        user_info: Extracted user information (will be updated in place)
        linked_event: Existing event if any

    Returns:
        True if product update was detected
    """
    subject = message_payload.get("subject") or ""
    body = message_payload.get("body") or ""
    text = f"{subject}\n{body}".strip().lower()
    if not text:
        return False

    participant_count = participants_from_event(linked_event)
    existing_additions = user_info.get("products_add")
    existing_removals = user_info.get("products_remove")
    existing_ops = bool(existing_additions or existing_removals)
    additions: List[Dict[str, Any]] = []
    removals: List[str] = []
    catalog = list_product_records()

    # Bulk removal detection: "remove all menus", "no food", "don't need any food"
    bulk_remove_menus = detect_bulk_menu_removal(text)
    if bulk_remove_menus:
        # Add special marker that apply_product_operations will handle
        removals.append("__BULK_REMOVE_MENUS__")
        # Also add specific menu names for more precise matching
        for menu in DINNER_MENU_OPTIONS:
            menu_name = str(menu.get("menu_name") or "").strip()
            if menu_name:
                removals.append(menu_name)
        # Also remove any catalog products with "menu" in category
        for record in catalog:
            cat = (record.category or "").lower()
            name = record.name or ""
            if "menu" in cat or "catering" in cat:
                removals.append(name)

    for record in catalog:
        tokens: List[str] = []
        primary = (record.name or "").strip().lower()
        if primary:
            tokens.append(primary)
            if not primary.endswith("s"):
                tokens.append(f"{primary}s")
            # Also match the last word of the product name
            primary_parts = primary.split()
            if primary_parts:
                last_primary = primary_parts[-1]
                if len(last_primary) >= 3 and last_primary not in _GENERIC_PRODUCT_TOKENS:
                    tokens.append(last_primary)
                    if not last_primary.endswith("s"):
                        tokens.append(f"{last_primary}s")
        for synonym in record.synonyms or []:
            synonym_token = str(synonym or "").strip().lower()
            if not synonym_token:
                continue
            tokens.append(synonym_token)
            if not synonym_token.endswith("s"):
                tokens.append(f"{synonym_token}s")
            synonym_parts = synonym_token.split()
            if synonym_parts:
                last_syn = synonym_parts[-1]
                if len(last_syn) >= 3 and last_syn not in _GENERIC_PRODUCT_TOKENS:
                    tokens.append(last_syn)
                    if not last_syn.endswith("s"):
                        tokens.append(f"{last_syn}s")

        matched_idx: Optional[int] = None
        matched_token: Optional[str] = None
        for token_candidate in tokens:
            idx = match_product_token(text, token_candidate)
            if idx is not None:
                matched_idx = idx
                matched_token = token_candidate
                break
        if matched_idx is None or matched_token is None:
            continue

        # Skip matches inside parentheses
        before = text[:matched_idx]
        if before.count("(") > before.count(")"):
            continue

        window_start = max(0, matched_idx - 80)
        window_end = min(len(text), matched_idx + len(matched_token) + 80)
        window = text[window_start:window_end]

        if contains_keyword(window, PRODUCT_REMOVE_KEYWORDS):
            removals.append(record.name)
            continue

        quantity = extract_quantity_from_window(window, matched_token)
        add_signal = contains_keyword(window, PRODUCT_ADD_KEYWORDS)
        if add_signal or quantity:
            payload: Dict[str, Any] = {"name": record.name}
            payload["quantity"] = quantity if quantity else 1
            additions.append(payload)

    # Also detect dinner menu selections/removals
    for menu in DINNER_MENU_OPTIONS:
        name = str(menu.get("menu_name") or "").strip()
        if not name:
            continue
        matched_idx = None
        matched_token = None
        for token_candidate in menu_token_candidates(name):
            idx = match_product_token(text, token_candidate)
            if idx is not None:
                matched_idx = idx
                matched_token = token_candidate
                break
        if matched_idx is None or matched_token is None:
            continue

        before = text[:matched_idx]
        if before.count("(") > before.count(")"):
            continue

        window_start = max(0, matched_idx - 80)
        window_end = min(len(text), matched_idx + len(matched_token) + 80)
        window = text[window_start:window_end]

        if contains_keyword(window, PRODUCT_REMOVE_KEYWORDS):
            removals.append(name)
            continue

        quantity = extract_quantity_from_window(window, matched_token) or 1
        additions.append({
            "name": name,
            "quantity": 1 if str(menu.get("unit") or "").strip().lower() == "per_event" else quantity,
            "unit_price": menu_price_value(menu.get("price")),
            "unit": menu.get("unit") or "per_event",
            "category": "Catering",
            "wish": "menu",
        })

    # Combine additions
    combined_additions: List[Dict[str, Any]] = []
    if existing_additions:
        combined_additions.extend(
            normalise_product_payload(existing_additions, participant_count=participant_count)
        )
    if additions:
        normalised = normalise_product_payload(additions, participant_count=participant_count)
        if normalised:
            combined_additions = (
                merge_product_requests(combined_additions, normalised) if combined_additions else normalised
            )
    if combined_additions:
        user_info["products_add"] = combined_additions

    # Combine removals
    combined_removals: List[str] = []
    removal_seen = set()
    if isinstance(existing_removals, list):
        for entry in existing_removals:
            name = entry.get("name") if isinstance(entry, dict) else entry
            text_name = str(name or "").strip()
            if text_name:
                lowered = text_name.lower()
                if lowered not in removal_seen:
                    removal_seen.add(lowered)
                    combined_removals.append(text_name)
    if removals:
        for name in removals:
            lowered = name.lower()
            if lowered not in removal_seen:
                removal_seen.add(lowered)
                combined_removals.append(name)
    if combined_removals:
        user_info["products_remove"] = combined_removals

    return bool(additions or removals or combined_additions or combined_removals or existing_ops)


# Backward-compatible aliases
_menu_price_value = menu_price_value
_detect_menu_choice = detect_menu_choice
_detect_bulk_menu_removal = detect_bulk_menu_removal
_detect_product_update_request = detect_product_update_request


__all__ = [
    "menu_price_value",
    "detect_menu_choice",
    "detect_bulk_menu_removal",
    "detect_product_update_request",
    "_menu_price_value",
    "_detect_menu_choice",
    "_detect_bulk_menu_removal",
    "_detect_product_update_request",
]
