from __future__ import annotations

from typing import Optional
from zoneinfo import ZoneInfo

__workflow_role__ = "CountryTimezone"

# Default timezone per country.
# Note: Some countries span multiple timezones (for example, US/CA/AU).
# In those cases this is a sensible fallback unless profile.timezone is set.
_COUNTRY_TIMEZONE_MAP = {
    "switzerland": "Europe/Zurich",
    "germany": "Europe/Berlin",
    "austria": "Europe/Vienna",
    "france": "Europe/Paris",
    "italy": "Europe/Rome",
    "spain": "Europe/Madrid",
    "united kingdom": "Europe/London",
    "ireland": "Europe/Dublin",
    "united states": "America/New_York",
    "canada": "America/Toronto",
    "mexico": "America/Mexico_City",
    "india": "Asia/Kolkata",
    "singapore": "Asia/Singapore",
    "united arab emirates": "Asia/Dubai",
    "saudi arabia": "Asia/Riyadh",
    "japan": "Asia/Tokyo",
    "china": "Asia/Shanghai",
    "australia": "Australia/Sydney",
    "new zealand": "Pacific/Auckland",
    "brazil": "America/Sao_Paulo",
    "south africa": "Africa/Johannesburg",
}

_COUNTRY_ALIASES = {
    "ch": "switzerland",
    "schweiz": "switzerland",
    "suisse": "switzerland",
    "svizzera": "switzerland",
    "de": "germany",
    "at": "austria",
    "fr": "france",
    "it": "italy",
    "es": "spain",
    "uk": "united kingdom",
    "gb": "united kingdom",
    "us": "united states",
    "usa": "united states",
    "ca": "canada",
    "mx": "mexico",
    "in": "india",
    "sg": "singapore",
    "uae": "united arab emirates",
    "ae": "united arab emirates",
    "sa": "saudi arabia",
    "jp": "japan",
    "cn": "china",
    "au": "australia",
    "nz": "new zealand",
    "br": "brazil",
    "za": "south africa",
}


def _normalize_token(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    token = str(value).strip().lower()
    if not token or token == "not specified":
        return None
    return token


def normalize_country_name(country: Optional[str]) -> Optional[str]:
    """Return normalized country key used by timezone mapping."""
    token = _normalize_token(country)
    if not token:
        return None
    return _COUNTRY_ALIASES.get(token, token)


def is_valid_timezone_name(timezone_name: Optional[str]) -> bool:
    """Return True if timezone_name is a valid IANA timezone."""
    token = _normalize_token(timezone_name)
    if not token:
        return False
    try:
        ZoneInfo(token)
        return True
    except Exception:
        return False


def timezone_for_country(country: Optional[str]) -> Optional[str]:
    """Return default timezone for a country, if known."""
    normalized = normalize_country_name(country)
    if not normalized:
        return None
    return _COUNTRY_TIMEZONE_MAP.get(normalized)


def resolve_timezone(country: Optional[str], explicit_timezone: Optional[str] = None) -> Optional[str]:
    """Resolve effective timezone from explicit profile timezone or country fallback."""
    if is_valid_timezone_name(explicit_timezone):
        return str(explicit_timezone).strip()
    return timezone_for_country(country)
