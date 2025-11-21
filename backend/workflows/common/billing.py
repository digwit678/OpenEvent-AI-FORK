from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from backend.workflows.nlu.parse_billing import parse_billing_address as _strict_parse_billing


BillingDetails = Dict[str, Optional[str]]


def empty_billing_details() -> BillingDetails:
    return {
        "name_or_company": None,
        "street": None,
        "postal_code": None,
        "city": None,
        "country": None,
        "vat": None,
        "raw": None,
    }


def parse_billing_address(raw: Optional[str], *, fallback_name: Optional[str] = None) -> BillingDetails:
    details = empty_billing_details()
    parsed, _ = _strict_parse_billing(raw, fallback_name=fallback_name)
    for key in details.keys():
        if key in parsed and parsed[key]:
            details[key] = parsed[key]
    return details


def update_billing_details(event_entry: Dict[str, Any]) -> None:
    if not event_entry:
        return
    event_data = event_entry.setdefault("event_data", {})
    raw = event_data.get("Billing Address")
    fallback = event_data.get("Company") or event_data.get("Name")
    current = event_entry.get("billing_details") or empty_billing_details()
    parsed, missing = _strict_parse_billing(raw, fallback_name=fallback)

    structured = empty_billing_details()
    for key in structured:
        value = parsed.get(key)
        if value:
            structured[key] = value
    if fallback and not structured.get("name_or_company"):
        structured["name_or_company"] = fallback

    merged = dict(current)
    for key, value in structured.items():
        if value:
            merged[key] = value
    event_entry["billing_details"] = merged
    if missing:
        event_entry.setdefault("billing_validation", {})["missing"] = list(missing)


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
