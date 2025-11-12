from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Tuple

BillingDetails = Dict[str, Optional[str]]

_POSTAL_CITY_RE = re.compile(
    r"^(?:(?P<prefix>[A-Za-z]{2})[-\s])?(?P<postal>\d{3,6})\s+(?P<city>[A-Za-zÄÖÜäöüßéèàçëïöü\-.'\s]+)$"
)
_VAT_RE = re.compile(r"(vat|mwst|tva|iva|uid)[:\s\-]*([A-Z0-9\-. ]+)", re.IGNORECASE)
_COUNTRY_ALIASES = {
    "switzerland": "Switzerland",
    "schweiz": "Switzerland",
    "suisse": "Switzerland",
    "svizzera": "Switzerland",
    "ch": "Switzerland",
    "germany": "Germany",
    "deutschland": "Germany",
    "france": "France",
    "fr": "France",
    "italy": "Italy",
    "italia": "Italy",
    "austria": "Austria",
    "österreich": "Austria",
    "liechtenstein": "Liechtenstein",
    "uk": "United Kingdom",
    "united kingdom": "United Kingdom",
    "england": "United Kingdom",
    "usa": "United States",
    "united states": "United States",
}


def parse_billing_address(raw: Optional[str], *, fallback_name: Optional[str] = None) -> Tuple[BillingDetails, List[str]]:
    """
    Best-effort normaliser for free-form billing addresses.

    Returns structured fields plus a list of required fields that are still missing.
    """

    text = _normalise_raw(raw)
    tokens = _tokenise_lines(text)

    details: BillingDetails = {
        "name_or_company": None,
        "street": None,
        "postal_code": None,
        "city": None,
        "country": None,
        "vat": None,
        "raw": text or None,
    }

    vat_value = _extract_vat(tokens)
    if vat_value:
        details["vat"] = vat_value

    country_value = _extract_country(tokens)
    if country_value:
        details["country"] = country_value

    postal, city = _extract_postal_city(tokens)
    if postal:
        details["postal_code"] = postal
    if city:
        details["city"] = city

    street = _extract_street(tokens)
    if street:
        details["street"] = street

    name = _extract_name(tokens, fallback_name)
    if name:
        details["name_or_company"] = name

    required = ["name_or_company", "street", "postal_code", "city", "country"]
    missing = [field for field in required if not details.get(field)]
    return details, missing


def _normalise_raw(raw: Optional[object]) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, dict):
        ordered: List[str] = []
        for key in ("name", "company", "street", "postal_code", "city", "country", "vat"):
            value = raw.get(key) if isinstance(raw, dict) else None
            if value:
                ordered.append(str(value))
        return "\n".join(ordered).strip()
    if isinstance(raw, (list, tuple, set)):
        return "\n".join(str(value).strip() for value in raw if value).strip()
    return str(raw).strip()


def _tokenise_lines(text: str) -> List[str]:
    if not text:
        return []
    normalised = text.replace("\r\n", "\n").replace(",", "\n").replace(";", "\n")
    tokens = [line.strip() for line in normalised.split("\n")]
    return [line for line in tokens if line]


def _extract_vat(tokens: List[str]) -> Optional[str]:
    for idx, line in enumerate(list(tokens)):
        match = _VAT_RE.search(line)
        if match:
            tokens.pop(idx)
            value = match.group(2).strip()
            return value or None
        if line.upper().startswith("CHE-") or line.upper().startswith("CH-"):
            tokens.pop(idx)
            return line.strip()
    return None


def _extract_country(tokens: List[str]) -> Optional[str]:
    for idx in range(len(tokens) - 1, -1, -1):
        text = tokens[idx]
        normalised = _normalise_country(text)
        if normalised:
            tokens.pop(idx)
            return normalised
    return None


def _normalise_country(text: str) -> Optional[str]:
    key = text.strip().lower()
    key = key.replace(".", "")
    if not key:
        return None
    if key in _COUNTRY_ALIASES:
        return _COUNTRY_ALIASES[key]
    if len(key) > 5 and key.endswith("land"):
        return text.strip().title()
    return None


def _extract_postal_city(tokens: List[str]) -> Tuple[Optional[str], Optional[str]]:
    for idx in range(len(tokens) - 1, -1, -1):
        line = tokens[idx]
        match = _POSTAL_CITY_RE.match(line)
        if match:
            tokens.pop(idx)
            postal = match.group("postal")
            city = match.group("city").strip().title()
            return postal, city
        split = _split_numeric_suffix(line)
        if split:
            tokens.pop(idx)
            return split
    return None, None


def _split_numeric_suffix(line: str) -> Optional[Tuple[str, str]]:
    digits = re.findall(r"\d{3,6}", line)
    if not digits:
        return None
    postal = digits[-1]
    before, _, after = line.partition(postal)
    city = after.strip() or before.strip()
    if city:
        return postal, city.title()
    return None


def _extract_street(tokens: List[str]) -> Optional[str]:
    for idx, line in enumerate(list(tokens)):
        if _looks_like_street(line):
            tokens.pop(idx)
            return line
    return tokens.pop(0) if tokens else None


def _looks_like_street(text: str) -> bool:
    if any(char.isdigit() for char in text):
        return True
    lowered = text.lower()
    return any(keyword in lowered for keyword in ("street", "strasse", "str.", "road", "avenue", "allee", "weg"))


def _extract_name(tokens: List[str], fallback: Optional[str]) -> Optional[str]:
    if tokens:
        candidate = tokens.pop(0)
        if not _looks_like_street(candidate):
            return candidate
        tokens.insert(0, candidate)
    return fallback
