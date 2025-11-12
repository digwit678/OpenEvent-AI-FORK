from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, List, Optional, Sequence

__all__ = [
    "MONTH_NAME_TO_INDEX",
    "MONTH_INDEX_TO_NAME",
    "week_window",
    "from_hints",
]

MONTH_NAME_TO_INDEX = {
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

MONTH_INDEX_TO_NAME = {
    1: "January",
    2: "February",
    3: "March",
    4: "April",
    5: "May",
    6: "June",
    7: "July",
    8: "August",
    9: "September",
    10: "October",
    11: "November",
    12: "December",
}


def week_window(
    year: int,
    month: int,
    week_index: int,
    *,
    weekdays_hint: Optional[Sequence[int]] = None,
    mon_fri_only: bool = True,
) -> List[str]:
    """Return ISO dates covering the requested week within a month."""

    if week_index < 1:
        raise ValueError("week_index must be >= 1")
    if month < 1 or month > 12:
        raise ValueError("month must be between 1 and 12")
    anchor = date(year, month, 1)
    offset = (7 - anchor.weekday()) % 7
    first_monday = anchor + timedelta(days=offset)
    window_start = first_monday + timedelta(days=7 * (week_index - 1))
    raw_dates: List[tuple[str, int, int]] = []
    for delta in range(7):
        current = window_start + timedelta(days=delta)
        iso_value = current.isoformat()
        raw_dates.append((iso_value, current.day, current.weekday()))
    filtered: List[str] = []
    for iso_value, _day, weekday in raw_dates:
        if mon_fri_only and weekday >= 5:
            continue
        filtered.append(iso_value)
    hint_days = _normalise_days(weekdays_hint or [])
    if hint_days:
        day_map = {day: iso for iso, day, _weekday in raw_dates}
        ordered: List[str] = []
        for day in hint_days:
            iso_value = day_map.get(day)
            if iso_value and iso_value in filtered and iso_value not in ordered:
                ordered.append(iso_value)
        remainder = [iso for iso in filtered if iso not in ordered]
        return ordered + remainder
    return filtered


def _coerce_month(month: str | int | None) -> Optional[int]:
    if month is None:
        return None
    if isinstance(month, int):
        return month if 1 <= month <= 12 else None
    token = month.strip().lower()
    return MONTH_NAME_TO_INDEX.get(token)


def _coerce_year(reference: date, month_index: int, week_index: int) -> int:
    candidate_year = reference.year
    window_dates = week_window(candidate_year, month_index, week_index)
    if window_dates[-1] < reference.isoformat():
        return candidate_year + 1
    return candidate_year


def _normalise_days(days: Iterable[int]) -> List[int]:
    result = sorted({day for day in days if 1 <= int(day) <= 31})
    return result


def from_hints(
    *,
    month: str | int | None,
    week_index: Optional[int],
    weekdays_hint: Optional[Sequence[int]] = None,
    reference: Optional[date] = None,
    mon_fri_only: bool = True,
) -> List[str]:
    """
    Derive ISO dates from month/week hints, defaulting to the next occurrence from reference.
    """

    month_index = _coerce_month(month)
    if month_index is None:
        return []
    resolved_reference = reference or date.today()
    hint_days = _normalise_days(weekdays_hint or [])
    inferred_week = week_index
    if inferred_week is None and hint_days:
        inferred_week = max(((hint_days[0] - 1) // 7) + 1, 1)
    if inferred_week is None:
        inferred_week = 1
    year = _coerce_year(resolved_reference, month_index, inferred_week)
    window_dates = week_window(
        year,
        month_index,
        inferred_week,
        weekdays_hint=hint_days,
        mon_fri_only=mon_fri_only,
    )
    if hint_days:
        day_map = {int(value.split("-")[2]): value for value in window_dates}
        ordered = [day_map[day] for day in hint_days if day in day_map]
        remainder = [value for value in window_dates if value not in ordered]
        return ordered + remainder
    return window_dates
