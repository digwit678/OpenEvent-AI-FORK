"""
Smart Shortcuts - Budget Parser.

Extracted from smart_shortcuts.py as part of S3 refactoring (Dec 2025).

This module handles budget information extraction and parsing from user input.
Budget can be specified as:
- Total budget ("CHF 500")
- Per-person budget ("CHF 50 per person")
- Dict with amount/currency/scope fields

Usage:
    from .budget_parser import extract_budget_info, parse_budget_value, parse_budget_text
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Dict, Optional

from .shortcuts_flags import _budget_default_currency, _budget_parse_strict

if TYPE_CHECKING:
    from .smart_shortcuts import _ShortcutPlanner


def extract_budget_info(planner: "_ShortcutPlanner") -> Optional[Dict[str, Any]]:
    """Extract budget information from user_info with priority ordering.

    Checks these fields in order:
    - budget_total (scope: total)
    - budget (scope: total)
    - budget_cap (scope: total)
    - budget_per_person (scope: per_person)

    Returns:
        Dict with amount, currency, scope, text if found; None otherwise.
    """
    candidates = [
        ("budget_total", "total"),
        ("budget", "total"),
        ("budget_cap", "total"),
        ("budget_per_person", "per_person"),
    ]
    for key, scope in candidates:
        if key not in planner.user_info:
            continue
        parsed = parse_budget_value(planner.user_info[key], scope_default=scope)
        if parsed:
            return parsed
    return None


def parse_budget_value(value: Any, scope_default: str) -> Optional[Dict[str, Any]]:
    """Parse a budget value that may be dict, number, or string.

    Args:
        value: The budget value (dict, int/float, or string)
        scope_default: Default scope if not specified ("total" or "per_person")

    Returns:
        Dict with amount, currency, scope, text if valid; None otherwise.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        amount = value.get("amount")
        currency = value.get("currency") or _budget_default_currency()
        scope = value.get("scope") or scope_default
        text = value.get("text")
        if amount is None and isinstance(text, str):
            parsed = parse_budget_text(text, scope)
            if parsed:
                return parsed
        if amount is None:
            return None
        try:
            amount_value = float(amount)
        except (TypeError, ValueError):
            return None
        display = text or f"{currency} {amount_value:g}"
        return {"amount": amount_value, "currency": currency, "scope": scope, "text": display}
    if isinstance(value, (int, float)):
        amount_value = float(value)
        currency = _budget_default_currency()
        display = f"{currency} {amount_value:g}"
        return {"amount": amount_value, "currency": currency, "scope": scope_default, "text": display}
    if isinstance(value, str):
        return parse_budget_text(value, scope_default)
    return None


def parse_budget_text(value: str, scope_default: str) -> Optional[Dict[str, Any]]:
    """Parse a budget string like 'CHF 500' or '50 per person'.

    Args:
        value: The budget text to parse
        scope_default: Default scope if not specified

    Returns:
        Dict with amount, currency, scope, text if valid; None otherwise.
    """
    text = (value or "").strip()
    if not text:
        return None
    pattern = re.compile(
        r"(?P<currency>[A-Za-z]{3})?\s*(?P<amount>\d+(?:[.,]\d{1,2})?)\s*(?P<scope>per\s*(?:person|guest|head)|total|overall)?",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return None
    currency = match.group("currency") or _budget_default_currency()
    if not match.group("currency") and _budget_parse_strict():
        return None
    try:
        amount = float(match.group("amount").replace(",", "."))
    except (TypeError, ValueError):
        return None
    scope_token = (match.group("scope") or scope_default or "").lower().strip()
    if scope_token.startswith("per"):
        scope = "per_person"
    elif scope_token in {"total", "overall"}:
        scope = "total"
    else:
        scope = scope_default
    display = text if match.group("currency") else f"{currency} {amount:g} {scope.replace('_', ' ')}".strip()
    return {"amount": amount, "currency": currency, "scope": scope, "text": display}


__all__ = [
    "extract_budget_info",
    "parse_budget_value",
    "parse_budget_text",
]
