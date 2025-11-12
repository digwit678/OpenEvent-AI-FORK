from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Tuple

BillingFields = Dict[str, Optional[str]]

_REQUIRED_FIELDS = ("name_or_company", "street", "postal_code", "city", "country")

_COUNTRY_ALIASES = {
    "Switzerland": {"switzerland", "schweiz", "suisse", "svizzera", "ch"},
    "Germany": {"germany", "deutschland", "de"},
    "France": {"france", "fr", "république française", "republique francaise"},
    "Italy": {"italy", "italia", "it"},
    "Austria": {"austria", "österreich", "osterreich", "at"},
    "Liechtenstein": {"liechtenstein", "li"},
}
_COUNTRY_ALIAS_FLAT = {alias for group in _COUNTRY_ALIASES.values() for alias in group}

_POSTAL_CITY_COMBINED = re.compile(
    r"^(?:CH[-\s])?(?P<postal>\d{4,6})[\s,]+(?P<city>[A-Za-zÀ-ÖØ-öø-ÿ' \-]+)$",
    re.IGNORECASE,
)
_POSTAL_CODE = re.compile(r"(?:CH[-\s])?(?P<postal>\d{4,6})")
_VAT_PATTERNS = [
    re.compile(r"\bCHE[-\s]?\d{3}\.\d{3}\.\d{3}(?:\s*MWST)?\b", re.IGNORECASE),
    re.compile(r"\b(?:VAT|UID|TVA|IVA)\s*[:\-]?\s*([A-Z0-9\.\- ]{5,})", re.IGNORECASE),
]
_LABELED_FIELD = re.compile(
    r"^\s*(?P<label>[A-Za-z ]{3,})\s*[:=\-]\s*(?P<value>.+?)\s*$",
    re.IGNORECASE,
)
_STREET_PATTERN = re.compile(r"^\s*(?P<street>.+?\d+\w*(?:[ /-]\w+)*)\s*$")


def parse_billing_address(raw: Optional[str], *, fallback_name: Optional[str] = None) -> Tuple[BillingFields, List[str]]:
    """
    Parse common billing-address formats into structured fields.

    Returns (fields, missing_required_fields).
    """

    details: BillingFields = {
        "name_or_company": None,
        "street": None,
        "postal_code": None,
        "city": None,
        "country": None,
        "vat": None,
        "raw": raw.strip() if isinstance(raw, str) else raw,
    }

    text = _normalise_text(raw)
    if not text:
        return details, list(_missing_fields(details, fallback_name))

    segments = _split_segments(text)
    labeled = _extract_labeled_values(segments)

    details["vat"] = _extract_vat(text, labeled)

    details["postal_code"], details["city"] = _extract_postal_city(segments, labeled)
    details["country"] = _extract_country(segments, labeled)

    details["street"] = _extract_street(segments, labeled)
    details["name_or_company"] = _extract_name(segments, labeled, fallback_name)

    missing_fields = list(_missing_fields(details, fallback_name))
    return details, missing_fields


def _normalise_text(raw: Optional[str]) -> str:
    if not isinstance(raw, str):
        return ""
    text = raw.replace("\r", "\n")
    return text.strip()


def _split_segments(text: str) -> List[str]:
    interim = text.replace(";", "\n")
    interim = interim.replace(",", "\n")
    lines = [line.strip() for line in interim.splitlines() if line.strip()]
    return lines


def _extract_labeled_values(segments: Sequence[str]) -> Dict[str, str]:
    labeled: Dict[str, str] = {}
    for line in segments:
        match = _LABELED_FIELD.match(line)
        if not match:
            continue
        label = match.group("label").strip().lower()
        value = match.group("value").strip()
        if not value:
            continue
        labeled[label] = value
    return labeled


def _extract_vat(text: str, labeled: Dict[str, str]) -> Optional[str]:
    for key in ("vat", "uid", "tva", "iva"):
        if key in labeled:
            return labeled[key]
    for pattern in _VAT_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(0)
    return None


def _extract_postal_city(
    segments: Sequence[str],
    labeled: Dict[str, str],
) -> Tuple[Optional[str], Optional[str]]:
    postal = None
    city = None

    if "postal code" in labeled or "zip" in labeled:
        candidate = labeled.get("postal code") or labeled.get("zip")
        if candidate:
            match = _POSTAL_CODE.search(candidate)
            if match:
                postal = match.group("postal")
    if "city" in labeled:
        city = labeled["city"]

    if postal and city:
        return postal, city

    for line in segments:
        combined = _POSTAL_CITY_COMBINED.match(line)
        if combined:
            return combined.group("postal"), combined.group("city").strip()

    for idx, line in enumerate(segments):
        number_only = _POSTAL_CODE.fullmatch(line)
        if number_only and idx + 1 < len(segments):
            next_line = segments[idx + 1]
            if not _LABELED_FIELD.match(next_line):
                return number_only.group("postal"), next_line

    return postal, city


def _extract_country(segments: Sequence[str], labeled: Dict[str, str]) -> Optional[str]:
    country = labeled.get("country")
    if country:
        return _normalise_country(country)

    for line in reversed(segments):
        normalized = _normalise_country(line)
        if normalized:
            return normalized
    return None


def _extract_street(segments: Sequence[str], labeled: Dict[str, str]) -> Optional[str]:
    for label in ("street", "address", "billing address", "address line 1"):
        if label in labeled:
            return labeled[label]

    for line in segments:
        if _LABELED_FIELD.match(line):
            continue
        if _POSTAL_CODE.search(line):
            continue
        if line.isdigit():
            continue
        if re.search(r"\d", line):
            match = _STREET_PATTERN.match(line)
            if match:
                return match.group("street").strip()
            return line
    return None


def _extract_name(segments: Sequence[str], labeled: Dict[str, str], fallback_name: Optional[str]) -> Optional[str]:
    for label in ("name", "company"):
        if label in labeled:
            return labeled[label]

    for line in segments:
        if _LABELED_FIELD.match(line):
            continue
        if re.search(r"\d", line):
            continue
        if line.lower() in _COUNTRY_ALIAS_FLAT:
            continue
        postal_match = _POSTAL_CODE.search(line)
        if postal_match:
            continue
        return line
    return fallback_name


def _normalise_country(candidate: str) -> Optional[str]:
    token = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ ]", "", candidate or "").strip()
    if not token:
        return None
    lowered = token.lower()
    for canonical, variants in _COUNTRY_ALIASES.items():
        if lowered in variants:
            return canonical
    return token.title()


def _missing_fields(details: BillingFields, fallback_name: Optional[str]) -> List[str]:
    missing: List[str] = []
    for field in _REQUIRED_FIELDS:
        value = details.get(field)
        if field == "name_or_company" and not value and fallback_name:
            continue
        if not value:
            missing.append(field)
    return missing
