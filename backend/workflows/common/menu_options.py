from __future__ import annotations

import re
import os
from typing import Any, Dict, List, Optional, Sequence

_MONTH_KEYWORDS = {
    "jan": "january",
    "january": "january",
    "feb": "february",
    "february": "february",
    "mar": "march",
    "march": "march",
    "apr": "april",
    "april": "april",
    "may": "may",
    "jun": "june",
    "june": "june",
    "jul": "july",
    "july": "july",
    "aug": "august",
    "august": "august",
    "sep": "september",
    "sept": "september",
    "september": "september",
    "oct": "october",
    "october": "october",
    "nov": "november",
    "november": "november",
    "dec": "december",
    "december": "december",
}

_MENU_KEY_PATTERN = re.compile(r"\b(?:menu|menus|menu options)\b")
_THREE_COURSE_PATTERN = re.compile(r"(?:three|3)[-\s]?course")


DINNER_MENU_OPTIONS: Sequence[Dict[str, Any]] = (
    {
        "menu_name": "Seasonal Garden Trio",
        "courses": 3,
        "vegetarian": True,
        "wine_pairing": True,
        "price": "CHF 92",
        "description": "Charred leek tart, truffle risotto, and citrus pavlova matched with Swiss whites.",
        "available_months": ["december", "january", "february", "march"],
        "season_label": "Available December–March",
        "notes": ["vegetarian"],
        "priority": 1,
    },
    {
        "menu_name": "Alpine Roots Degustation",
        "courses": 3,
        "vegetarian": True,
        "wine_pairing": True,
        "price": "CHF 105",
        "description": "Roasted beet mille-feuille, herb gnocchi, and warm chocolate tart with alpine wine pairing.",
        "available_months": ["november", "december", "january", "february"],
        "season_label": "Available November–February",
        "notes": ["vegetarian"],
        "priority": 2,
    },
    {
        "menu_name": "Lakeview Signature Journey",
        "courses": 3,
        "vegetarian": False,
        "wine_pairing": True,
        "price": "CHF 118",
        "description": "Lake char crudo, veal tenderloin, and Swiss meringue finale with matching wines.",
        "available_months": ["february", "march", "april"],
        "season_label": "Available February–April",
        "notes": ["includes meat & seafood"],
        "priority": 3,
    },
)


def _normalize_month(month: Optional[str]) -> Optional[str]:
    if not month:
        return None
    token = str(month).strip().lower()
    return _MONTH_KEYWORDS.get(token, token or None)


def _contains_menu_keyword(text: str) -> bool:
    return bool(_MENU_KEY_PATTERN.search(text))


def extract_menu_request(message_text: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parse incoming text and detect if it contains a menu-related question."""

    if not message_text:
        return None
    lowered = message_text.lower()
    if not _contains_menu_keyword(lowered):
        return None

    vegetarian = any(token in lowered for token in ("vegetarian", "veg-friendly", "veggie", "plant-based", "meatless"))
    vegan = "vegan" in lowered
    if vegan:
        vegetarian = True
    wine_pairing = "wine" in lowered or "pairing" in lowered or "paired wines" in lowered
    three_course = bool(_THREE_COURSE_PATTERN.search(lowered))

    month_hint: Optional[str] = None
    for token, canonical in _MONTH_KEYWORDS.items():
        if token in lowered:
            month_hint = canonical
            break

    return {
        "vegetarian": vegetarian,
        "wine_pairing": wine_pairing,
        "three_course": three_course,
        "month": month_hint,
        "menu_requested": True,
    }


def _menu_matches_request(menu: Dict[str, Any], request: Dict[str, Any]) -> bool:
    if request.get("vegetarian") and not menu.get("vegetarian"):
        return False
    if request.get("three_course") and menu.get("courses") not in (None, 3):
        return False
    if request.get("wine_pairing") and not menu.get("wine_pairing"):
        return False
    return True


def select_menu_options(
    request: Dict[str, Any],
    *,
    month_hint: Optional[str] = None,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """Filter dinner menus based on the client request."""

    month_token = _normalize_month(month_hint or request.get("month"))
    filtered: List[Dict[str, Any]] = []

    for menu in DINNER_MENU_OPTIONS:
        if not _menu_matches_request(menu, request):
            continue
        menu_months = menu.get("available_months") or []
        if month_token and menu_months and month_token not in menu_months:
            continue
        filtered.append(dict(menu))

    if not filtered and month_token:
        for menu in DINNER_MENU_OPTIONS:
            if not _menu_matches_request(menu, request):
                continue
            filtered.append(dict(menu))

    filtered.sort(key=lambda item: (item.get("priority", 100), item.get("price") or ""))
    return filtered[:limit]


def build_menu_title(request: Dict[str, Any]) -> str:
    """Compose a heading describing the detected menu request."""

    segments: List[str] = []
    if request.get("vegetarian"):
        segments.append("Vegetarian")
    else:
        segments.append("Dinner")

    if request.get("three_course"):
        segments.append("three-course menus")
    else:
        segments.append("menu options")

    base = " ".join(segments)
    if request.get("wine_pairing"):
        return f"{base} with wine pairings:"
    return f"{base} we can offer:"


def _normalise_price(value: Any) -> str:
    if value is None:
        return "CHF ?"
    if isinstance(value, (int, float)):
        if float(value).is_integer():
            return f"CHF {int(value)}"
        return f"CHF {value:.2f}"
    text = str(value).strip()
    if not text:
        return "CHF ?"
    lowered = text.lower()
    if lowered.startswith("chf"):
        stripped = text[3:].strip()
        return f"CHF {stripped}" if stripped else "CHF ?"
    return f"CHF {text}"


def format_menu_line(menu: Dict[str, Any], *, month_hint: Optional[str] = None) -> str:
    """Render a friendly bullet point for a dinner menu option."""

    name = str(menu.get("menu_name") or "").strip()
    if not name:
        return ""
    price_text = _normalise_price(menu.get("price"))

    notes: List[str] = []
    if menu.get("wine_pairing"):
        notes.append("wine pairings included")
    if menu.get("vegetarian"):
        notes.append("vegetarian")
    notes.extend(menu.get("notes") or [])

    season_label = menu.get("season_label")
    if season_label:
        notes.append(str(season_label))
    elif month_hint:
        menu_months = {str(month).lower() for month in menu.get("available_months") or []}
        token = _normalize_month(month_hint)
        if token and (not menu_months or token in menu_months):
            notes.append(f"available in {token.capitalize()}")

    notes_deduped: List[str] = []
    for entry in notes:
        clean = str(entry).strip()
        if clean and clean not in notes_deduped:
            notes_deduped.append(clean)

    line = f"- {name} — {price_text} per guest"
    if notes_deduped:
        line += f" ({'; '.join(notes_deduped)})"
    line += "."

    description = str(menu.get("description") or "").strip()
    if description:
        line += f" {description}"
    return line


def build_menu_payload(
    message_text: Optional[str],
    *,
    context_month: Optional[str] = None,
    limit: int = 3,
    allow_context_fallback: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """Return a structured payload describing menu options for the general Q&A block."""

    request = extract_menu_request(message_text)
    if not request:
        return None

    request_month = _normalize_month(request.get("month"))
    primary_month = request_month
    link_context = ALLOW_CONTEXTUAL_HINTS if allow_context_fallback is None else allow_context_fallback
    context_hint = _normalize_month(context_month)
    if not primary_month and link_context and context_hint:
        primary_month = context_hint

    options = select_menu_options(request, month_hint=primary_month, limit=limit)
    if not options:
        return None

    rows: List[Dict[str, Any]] = []
    for menu in options:
        rows.append(
            {
                "menu_name": menu.get("menu_name"),
                "courses": menu.get("courses"),
                "vegetarian": menu.get("vegetarian"),
                "wine_pairing": menu.get("wine_pairing"),
                "price": menu.get("price"),
                "notes": menu.get("notes"),
                "description": menu.get("description"),
                "available_months": menu.get("available_months"),
                "season_label": menu.get("season_label"),
            }
        )

    where_clauses: List[str] = []
    if request.get("three_course"):
        where_clauses.append("courses=3")
    if request.get("vegetarian"):
        where_clauses.append("vegetarian=true")
    if request.get("wine_pairing"):
        where_clauses.append("wine_pairing=true")
    if request_month:
        where_clauses.append(f"available_month='{request_month.capitalize()}'")

    payload: Dict[str, Any] = {
        "select_expr": "SELECT menu_name, courses, vegetarian, wine_pairing, price",
        "where_clauses": where_clauses,
        "rows": rows,
        "title": build_menu_title(request),
        "request": request,
    }
    if primary_month:
        payload["month"] = primary_month
        if link_context and primary_month == context_hint and primary_month != request_month:
            payload["context_linked"] = True
    if request_month:
        payload["request_month"] = request_month
    return payload


__all__ = [
    "build_menu_payload",
    "build_menu_title",
    "extract_menu_request",
    "format_menu_line",
    "select_menu_options",
]
_LINK_CONTEXT_ENV = os.getenv("OPENEVENT_MENU_CONTEXT_LINK", "").strip()
ALLOW_CONTEXTUAL_HINTS = _LINK_CONTEXT_ENV.lower() in {"1", "true", "yes"}
# TODO(openevent-team): Revisit whether contextual hints should be linked by default.
