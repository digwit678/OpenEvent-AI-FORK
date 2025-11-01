"""Utility helpers for parsing human-friendly dates and time ranges."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from typing import Optional, Tuple

from zoneinfo import ZoneInfo

TZ_ZURICH = ZoneInfo("Europe/Zurich")

_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

_DATE_NUMERIC = re.compile(
    r"\b(?P<day>\d{1,2})[./](?P<month>\d{1,2})[./](?P<year>\d{2,4})\b"
)
_DATE_ISO = re.compile(
    r"\b(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})\b"
)
_DATE_TEXTUAL_DMY = re.compile(
    r"\b(?P<day>\d{1,2})(?:st|nd|rd|th)?\s+(?P<month>[A-Za-z]{3,9})(?:\s*,?\s*(?P<year>\d{2,4}))?\b"
)
_DATE_TEXTUAL_MDY = re.compile(
    r"\b(?P<month>[A-Za-z]{3,9})\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?(?:\s*,?\s*(?P<year>\d{2,4}))?\b"
)

_TIME_RANGE = re.compile(
    r"(?P<s_hour>\d{1,2})(?::(?P<s_min>\d{2}))?\s*(?P<s_suffix>am|pm|a\.m\.|p\.m\.|uhr|h)?"
    r"\s*(?:-|–|—|to|till|until|bis)\s*"
    r"(?P<e_hour>\d{1,2})(?::(?P<e_min>\d{2}))?\s*(?P<e_suffix>am|pm|a\.m\.|p\.m\.|uhr|h)?",
    re.IGNORECASE,
)

_TIME_24H = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")


def parse_first_date(text: str, *, fallback_year: Optional[int] = None) -> Optional[date]:
    """Parse the first recognizable date within ``text``."""

    for pattern in (_DATE_NUMERIC, _DATE_ISO):
        match = pattern.search(text)
        if not match:
            continue
        parts = match.groupdict()
        year = int(parts["year"])
        if year < 100:
            year += 2000
        month = int(parts["month"])
        day = int(parts["day"])
        try:
            return date(year, month, day)
        except ValueError:
            continue

    for pattern in (_DATE_TEXTUAL_DMY, _DATE_TEXTUAL_MDY):
        match = pattern.search(text)
        if not match:
            continue
        parts = match.groupdict()
        month_token = parts["month"].lower()
        month = _MONTHS.get(month_token)
        if month:
            try:
                year_str = parts.get("year")
                if year_str:
                    year = int(year_str) if len(year_str) == 4 else 2000 + int(year_str)
                elif fallback_year is not None:
                    year = fallback_year
                else:
                    year = datetime.utcnow().year
                day = int(parts["day"])
                return date(year, month, day)
            except ValueError:
                return None
    return None


def to_ddmmyyyy(value: date | str) -> Optional[str]:
    """Format supported date inputs into DD.MM.YYYY."""

    if isinstance(value, str):
        parsed = parse_first_date(value)
        if not parsed:
            return None
        return parsed.strftime("%d.%m.%Y")
    if isinstance(value, date):
        return value.strftime("%d.%m.%Y")
    return None


def to_iso_date(ddmmyyyy: str) -> Optional[str]:
    """Convert ``DD.MM.YYYY`` into ISO ``YYYY-MM-DD``."""

    try:
        parsed = datetime.strptime(ddmmyyyy, "%d.%m.%Y").date()
    except ValueError:
        return None
    return parsed.isoformat()


def parse_time_range(text: str) -> Tuple[Optional[time], Optional[time], bool]:
    """
    Extract a time range from ``text``.

    Returns a tuple of (start_time, end_time, matched), where ``matched`` signals
    whether any span was identified (even if parsing failed).
    """

    text_norm = text or ""
    for match in _TIME_RANGE.finditer(text_norm):
        start = _build_time(
            match.group("s_hour"),
            match.group("s_min"),
            match.group("s_suffix"),
            fallback_suffix=match.group("e_suffix"),
        )
        end = _build_time(
            match.group("e_hour"),
            match.group("e_min"),
            match.group("e_suffix"),
            fallback_suffix=match.group("s_suffix"),
        )
        if start and end:
            end = _adjust_end_if_needed(start, end)
            return start, end, True
        if start or end:
            return start, end, True

    times = _TIME_24H.findall(text_norm)
    if len(times) >= 2:
        start_hour, start_min = map(int, times[0])
        end_hour, end_min = map(int, times[1])
        start = time(start_hour, start_min)
        end = time(end_hour, end_min)
        end = _adjust_end_if_needed(start, end)
        return start, end, True
    return None, None, False


def build_window_iso(iso_date: str, start: time, end: time) -> Tuple[str, str]:
    """Compose timezone-aware ISO start/end from date and time components."""

    day = datetime.fromisoformat(iso_date)
    start_dt = datetime.combine(day.date(), start, tzinfo=TZ_ZURICH)
    end_dt = datetime.combine(day.date(), end, tzinfo=TZ_ZURICH)
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)
    return start_dt.isoformat(), end_dt.isoformat()


def _build_time(hour_str: Optional[str], minute_str: Optional[str], suffix: Optional[str], fallback_suffix: Optional[str]) -> Optional[time]:
    if hour_str is None:
        return None
    try:
        hour = int(hour_str)
    except ValueError:
        return None
    if not 0 <= hour <= 23:
        if suffix and suffix.lower().startswith(("a", "p")):
            hour %= 12
        else:
            return None
    minute = 0
    if minute_str:
        try:
            minute = int(minute_str)
        except ValueError:
            return None
    suffix_norm = (suffix or "").lower().rstrip(".")
    if suffix_norm in {"pm", "p", "p m"}:
        if hour < 12:
            hour += 12
    elif suffix_norm in {"am", "a", "a m"}:
        if hour == 12:
            hour = 0
    elif suffix_norm in {"uhr", "h"}:
        pass
    elif not suffix_norm and fallback_suffix:
        fallback_norm = fallback_suffix.lower().rstrip(".")
        if fallback_norm in {"pm", "p", "p m"} and hour < 12:
            hour += 12
        elif fallback_norm in {"am", "a", "a m"} and hour == 12:
            hour = 0
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def _adjust_end_if_needed(start: time, end: time) -> time:
    if end > start:
        return end
    start_dt = datetime.combine(date.today(), start, tzinfo=TZ_ZURICH)
    end_dt = datetime.combine(date.today(), end, tzinfo=TZ_ZURICH)
    if end_dt <= start_dt:
        end_dt += timedelta(hours=12)
    return end_dt.time()


__all__ = [
    "TZ_ZURICH",
    "parse_first_date",
    "to_ddmmyyyy",
    "to_iso_date",
    "parse_time_range",
    "build_window_iso",
]
