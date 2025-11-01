from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional


BillingDetails = Dict[str, Optional[str]]


def empty_billing_details() -> BillingDetails:
    return {
        "name_or_company": None,
        "street": None,
        "postal_code": None,
        "city": None,
        "country": None,
        "raw": None,
    }


_POSTAL_CITY_RE = re.compile(r"^(?P<postal>\d{4,6})\s*(?P<city>.*)$")


def parse_billing_address(raw: Optional[str], *, fallback_name: Optional[str] = None) -> BillingDetails:
    details = empty_billing_details()
    if fallback_name:
        details["name_or_company"] = fallback_name.strip() or None
    if not raw:
        return details

    details["raw"] = raw.strip()
    tokens = _tokenize_address(raw)
    if not tokens:
        return details

    candidate_name = tokens[0]
    for token in tokens:
        normalized = token.strip()
        if not normalized:
            continue
        lower = normalized.lower()
        if _looks_like_postal_city(normalized):
            match = _POSTAL_CITY_RE.match(normalized)
            if match:
                details["postal_code"] = match.group("postal").strip()
                city_candidate = match.group("city").strip()
                if city_candidate:
                    details["city"] = city_candidate
            continue
        if details["street"] is None and _looks_like_street(normalized):
            details["street"] = normalized
            continue
        if details["city"] is None and _looks_like_city(normalized):
            details["city"] = normalized
            continue
        if details["country"] is None and _looks_like_country(lower):
            details["country"] = normalized
            continue

    if not details["name_or_company"]:
        details["name_or_company"] = candidate_name if candidate_name != details.get("street") else fallback_name
    return details


def update_billing_details(event_entry: Dict[str, Any]) -> None:
    if not event_entry:
        return
    event_data = event_entry.setdefault("event_data", {})
    raw = event_data.get("Billing Address")
    fallback = event_data.get("Company") or event_data.get("Name")
    current = event_entry.get("billing_details") or empty_billing_details()
    parsed = parse_billing_address(raw, fallback_name=fallback)

    merged = dict(current)
    for key, value in parsed.items():
        if value:
            merged[key] = value
    if fallback and not merged.get("name_or_company"):
        merged["name_or_company"] = fallback
    event_entry["billing_details"] = merged


def missing_billing_fields(event_entry: Dict[str, Any]) -> List[str]:
    details = event_entry.get("billing_details") or {}
    required = ["name_or_company", "street", "postal_code", "city", "country"]
    missing: List[str] = []
    for field in required:
        value = details.get(field)
        if not value or not str(value).strip():
            missing.append(field)
    return missing


def billing_prompt_for_missing_fields(fields: Iterable[str]) -> str:
    field_labels = {
        "name_or_company": "company or billing name",
        "street": "street address",
        "postal_code": "postal code",
        "city": "city",
        "country": "country",
    }
    labels = [field_labels.get(f, f) for f in fields]
    if not labels:
        return ""
    if len(labels) == 1:
        joined = labels[0]
    elif len(labels) == 2:
        joined = " and ".join(labels)
    else:
        joined = ", ".join(labels[:-1]) + f", and {labels[-1]}"
    return (
        f"Before I finalise, could you share the {joined}? "
        "Feel free to reply in one line (e.g., \"Postal code: 8000; Country: Switzerland\")."
    )


def _tokenize_address(raw: str) -> List[str]:
    normalized = raw.replace("\n", ",").replace(";", ",")
    return [token.strip() for token in normalized.split(",") if token.strip()]


def _looks_like_postal_city(token: str) -> bool:
    return bool(_POSTAL_CITY_RE.match(token.strip()))


def _looks_like_street(token: str) -> bool:
    return any(ch.isdigit() for ch in token) and any(ch.isalpha() for ch in token)


def _looks_like_city(token: str) -> bool:
    stripped = token.strip()
    if not stripped:
        return False
    has_digit = any(ch.isdigit() for ch in stripped)
    return not has_digit and len(stripped.split()) <= 3


def _looks_like_country(lower_token: str) -> bool:
    return lower_token in {
        "switzerland",
        "germany",
        "austria",
        "france",
        "italy",
        "liechtenstein",
        "united kingdom",
        "uk",
        "usa",
        "united states",
        "spain",
        "portugal",
    }
