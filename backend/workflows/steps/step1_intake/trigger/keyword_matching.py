"""Keyword and product token matching helpers for Step 1.

Extracted from step1_handler.py as part of I1 refactoring (Dec 2025).
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

# Product operation keyword tuples
PRODUCT_ADD_KEYWORDS: Tuple[str, ...] = (
    "add",
    "include",
    "plus",
    "extra",
    "another",
    "additional",
    "also add",
    "bring",
    "upgrade",
)

PRODUCT_REMOVE_KEYWORDS: Tuple[str, ...] = (
    "remove",
    "without",
    "drop",
    "exclude",
    "skip",
    "no ",
    "minus",
    "cut",
)

# Regex caches (module-level for performance)
_KEYWORD_REGEX_CACHE: Dict[str, re.Pattern[str]] = {}
_PRODUCT_TOKEN_REGEX_CACHE: Dict[str, re.Pattern[str]] = {}


def keyword_regex(keyword: str) -> re.Pattern[str]:
    """Build and cache a word-boundary regex for a keyword."""
    cached = _KEYWORD_REGEX_CACHE.get(keyword)
    if cached:
        return cached
    pattern = re.escape(keyword.strip())
    pattern = pattern.replace(r"\ ", r"\s+")
    regex = re.compile(rf"\b{pattern}\b")
    _KEYWORD_REGEX_CACHE[keyword] = regex
    return regex


def contains_keyword(window: str, keywords: Tuple[str, ...]) -> bool:
    """Check if text window contains any of the given keywords."""
    normalized = window.lower()
    for keyword in keywords:
        token = keyword.strip()
        if not token:
            continue
        if keyword_regex(token).search(normalized):
            return True
    return False


def product_token_regex(token: str) -> re.Pattern[str]:
    """Build and cache a regex for matching product name tokens."""
    cached = _PRODUCT_TOKEN_REGEX_CACHE.get(token)
    if cached:
        return cached
    parts = re.split(r"[\s\-]+", token.strip())
    escaped_parts = [re.escape(part) for part in parts if part]
    if not escaped_parts:
        pattern = re.escape(token.strip())
    else:
        pattern = r"[\s\-]+".join(escaped_parts)
    regex = re.compile(rf"\b{pattern}\b")
    _PRODUCT_TOKEN_REGEX_CACHE[token] = regex
    return regex


def match_product_token(text: str, token: str) -> Optional[int]:
    """Find the first match position of a product token in text."""
    regex = product_token_regex(token)
    match = regex.search(text)
    if match:
        return match.start()
    return None


def extract_quantity_from_window(window: str, token: str) -> Optional[int]:
    """Extract quantity like '3x product' or '3 units of product' from text window."""
    escaped_token = re.escape(token.strip())
    pattern = re.compile(
        rf"(\d{{1,3}})\s*(?:x|times|pcs|pieces|units)?\s*(?:of\s+)?{escaped_token}s?",
        re.IGNORECASE,
    )
    match = pattern.search(window)
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def menu_token_candidates(name: str) -> List[str]:
    """Return token variants to match a dinner menu mention in free text."""
    tokens: List[str] = []
    lowered = name.strip().lower()
    if not lowered:
        return tokens
    tokens.append(lowered)
    if not lowered.endswith("s"):
        tokens.append(f"{lowered}s")
    parts = lowered.split()
    if parts:
        last = parts[-1]
        if len(last) >= 3:
            tokens.append(last)
            if not last.endswith("s"):
                tokens.append(f"{last}s")
    return tokens
