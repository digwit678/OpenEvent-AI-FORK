from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Set

__all__ = ["extract_preferences"]

_TOKEN_SPLIT = re.compile(r"[,\n;/]+")
_WORD_SPLIT = re.compile(r"[^a-z0-9]+", re.IGNORECASE)

_DEFAULT_HINT = "catering available"


def _clean_tokens(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    tokens: List[str] = []
    for segment in _TOKEN_SPLIT.split(str(raw)):
        lowered = segment.strip().lower()
        if not lowered:
            continue
        tokens.append(lowered)
    return tokens


def _normalise_keyword(text: str) -> Optional[str]:
    cleaned = _WORD_SPLIT.sub(" ", text or "").strip().lower()
    if not cleaned:
        return None
    if len(cleaned) <= 2:
        return None
    return cleaned


def _extend_keywords(target: Set[str], values: Iterable[str]) -> None:
    for value in values:
        normalised = _normalise_keyword(value)
        if normalised:
            target.add(normalised)


def extract_preferences(user_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Derive lightweight room and catering preferences from captured user info.

    The output structure:
        {
            "wish_products": ["wine pairing", ...],
            "keywords": ["red wine", "long table"],
            "default_hint": "catering available",
        }
    """

    preferences: Dict[str, Any] = {"default_hint": _DEFAULT_HINT}
    wish_products: List[str] = []
    keywords: Set[str] = set()

    products_field = user_info.get("products_add") or user_info.get("wishlist_products")
    if isinstance(products_field, list):
        for item in products_field:
            if isinstance(item, dict):
                name = item.get("name")
            else:
                name = item
            if not name:
                continue
            label = str(name).strip()
            if not label:
                continue
            wish_products.append(label)
            normalized = _normalise_keyword(label)
            if normalized:
                keywords.add(normalized)

    catering_value = user_info.get("catering") or user_info.get("catering_preference")
    catering_value = catering_value or user_info.get("catering_preferences")
    if catering_value:
        _extend_keywords(keywords, _clean_tokens(str(catering_value)))

    layout_pref = user_info.get("layout") or user_info.get("seating_layout")
    if layout_pref:
        normalized = _normalise_keyword(str(layout_pref))
        if normalized:
            keywords.add(normalized)

    requirement_tokens: List[str] = []
    for field in ("notes", "special_requirements", "requirements_text"):
        value = user_info.get(field)
        if value:
            requirement_tokens.extend(_clean_tokens(str(value)))
    if requirement_tokens:
        _extend_keywords(keywords, requirement_tokens)

    if wish_products:
        preferences["wish_products"] = list(dict.fromkeys(wish_products))
    if keywords:
        preferences["keywords"] = list(sorted(keywords))
    return preferences
