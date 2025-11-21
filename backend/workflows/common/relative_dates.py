from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Iterable, List, Optional, Sequence, Set, Tuple

_WEEKDAY_NAME_TO_INDEX = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}

_ORDINAL_WORD_TO_INDEX = {
    "first": 1,
    "1st": 1,
    "second": 2,
    "2nd": 2,
    "third": 3,
    "3rd": 3,
    "fourth": 4,
    "4th": 4,
    "fifth": 5,
    "5th": 5,
    "last": -1,
}


def resolve_relative_date(
    text: str,
    reference_day: date,
    *,
    candidates: Optional[Sequence[object]] = None,
) -> Optional[date]:
    """Resolve relative date phrases (e.g. “next Friday”) into absolute dates."""

    normalized_text = (text or "").strip().lower()
    if not normalized_text:
        return None

    general_weekdays, next_weekdays, this_weekdays = _extract_weekday_signals(normalized_text)
    month_mentions = _extract_month_mentions(normalized_text)
    ordinal = _extract_week_ordinal(normalized_text)
    has_week_keyword = "week" in normalized_text
    has_week_after_next = "week after next" in normalized_text
    has_next_week = "next week" in normalized_text or "coming week" in normalized_text
    if has_week_after_next:
        has_next_week = False
    has_this_week = "this week" in normalized_text
    has_next_month = "next month" in normalized_text
    has_this_month = "this month" in normalized_text

    signal_present = (
        general_weekdays
        or next_weekdays
        or this_weekdays
        or month_mentions
        or ordinal is not None
        or has_next_week
        or has_this_week
        or has_week_after_next
        or has_next_month
        or has_this_month
    )
    if not signal_present or not (general_weekdays or next_weekdays or this_weekdays):
        return None

    candidate_dates = _normalize_candidates(candidates)
    if not candidate_dates:
        candidate_dates = _generate_candidate_dates(reference_day, general_weekdays)

    best_date = _select_best_candidate(
        candidate_dates,
        reference_day,
        general_weekdays,
        next_weekdays,
        this_weekdays,
        month_mentions,
        ordinal,
        has_week_keyword,
        has_week_after_next,
        has_next_week,
        has_this_week,
        has_next_month,
        has_this_month,
    )
    return best_date


def _extract_weekday_signals(text: str) -> Tuple[Set[int], Set[int], Set[int]]:
    general: Set[int] = set()
    next_qualifiers: Set[int] = set()
    this_qualifiers: Set[int] = set()
    for idx, tokens in _weekday_tokens().items():
        for token in tokens:
            base_pattern = rf"\b{re.escape(token)}s?\b"
            if re.search(base_pattern, text):
                general.add(idx)
            if re.search(rf"\bnext\s+{re.escape(token)}s?\b", text):
                next_qualifiers.add(idx)
            if re.search(rf"\b{re.escape(token)}s?\s+next\s+week\b", text):
                next_qualifiers.add(idx)
            if re.search(rf"\bcoming\s+{re.escape(token)}s?\b", text):
                next_qualifiers.add(idx)
            if re.search(rf"\bthis\s+{re.escape(token)}s?\b", text):
                this_qualifiers.add(idx)
            if re.search(rf"\b{re.escape(token)}s?\s+this\s+week\b", text):
                this_qualifiers.add(idx)
    return general, next_qualifiers, this_qualifiers


def _extract_month_mentions(text: str) -> Set[int]:
    mentions: Set[int] = set()
    month_map = {
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
    for token, idx in month_map.items():
        if re.search(rf"\b{re.escape(token)}\b", text):
            mentions.add(idx)
    return mentions


def _extract_week_ordinal(text: str) -> Optional[int]:
    for token, index in _ORDINAL_WORD_TO_INDEX.items():
        if re.search(rf"\b{re.escape(token)}\b", text):
            return index
    return None


def _weekday_tokens() -> dict[int, Tuple[str, ...]]:
    mapping: dict[int, Set[str]] = {}
    for token, idx in _WEEKDAY_NAME_TO_INDEX.items():
        mapping.setdefault(idx, set()).add(token)
    return {
        idx: tuple(sorted(tokens, key=len, reverse=True))
        for idx, tokens in mapping.items()
    }


def _normalize_candidates(candidates: Optional[Sequence[object]]) -> List[date]:
    if not candidates:
        return []
    results: List[date] = []
    for value in candidates:
        candidate = _to_date(value)
        if candidate and candidate not in results:
            results.append(candidate)
    return results


def _generate_candidate_dates(reference_day: date, weekdays: Iterable[int]) -> List[date]:
    target_weekdays = set(weekdays)
    limit_days = 450
    results: List[date] = []
    cursor = reference_day
    for offset in range(limit_days + 1):
        current = cursor + timedelta(days=offset)
        if target_weekdays and current.weekday() not in target_weekdays:
            continue
        results.append(current)
    return results


def _select_best_candidate(
    candidate_dates: Sequence[date],
    reference_day: date,
    general_weekdays: Set[int],
    next_weekdays: Set[int],
    this_weekdays: Set[int],
    month_mentions: Set[int],
    ordinal: Optional[int],
    has_week_keyword: bool,
    has_week_after_next: bool,
    has_next_week: bool,
    has_this_week: bool,
    has_next_month: bool,
    has_this_month: bool,
) -> Optional[date]:
    week_start = reference_day - timedelta(days=reference_day.weekday())
    this_week_range = (week_start, week_start + timedelta(days=6))
    next_week_range = (week_start + timedelta(days=7), week_start + timedelta(days=13))
    week_after_next_range = (week_start + timedelta(days=14), week_start + timedelta(days=20))
    next_month_year, next_month = _next_month_reference(reference_day)

    best_date: Optional[date] = None
    best_score = -1

    for date_value in candidate_dates:
        score = 0

        if general_weekdays:
            if date_value.weekday() in general_weekdays:
                score += 10
            else:
                continue

        if next_weekdays:
            if (
                date_value.weekday() in next_weekdays
                and next_week_range[0] <= date_value <= next_week_range[1]
            ):
                score += 8
            else:
                continue

        if this_weekdays:
            if (
                date_value.weekday() in this_weekdays
                and this_week_range[0] <= date_value <= this_week_range[1]
            ):
                score += 8
            else:
                continue

        if has_week_after_next:
            if week_after_next_range[0] <= date_value <= week_after_next_range[1]:
                score += 5
            else:
                continue

        if has_next_week and not next_weekdays:
            if next_week_range[0] <= date_value <= next_week_range[1]:
                score += 4
            else:
                continue

        if has_this_week and not this_weekdays:
            if this_week_range[0] <= date_value <= this_week_range[1]:
                score += 3
            else:
                continue

        if month_mentions:
            if date_value.month in month_mentions:
                score += 5
            else:
                continue

        if has_next_month:
            if date_value.year == next_month_year and date_value.month == next_month:
                score += 4
            else:
                continue

        if has_this_month:
            if date_value.year == reference_day.year and date_value.month == reference_day.month:
                score += 2
            else:
                continue

        if ordinal is not None and has_week_keyword:
            week_index = _week_of_month(date_value)
            if ordinal == -1:
                if _is_last_week_of_month(date_value):
                    score += 3
                else:
                    continue
            else:
                if week_index == ordinal:
                    score += 3
                else:
                    continue

        if score <= 0:
            continue

        proximity = abs((date_value - reference_day).days)
        if proximity <= 30:
            score += max(0, 3 - proximity // 7)

        if best_date is None or score > best_score or (score == best_score and date_value < best_date):
            best_date = date_value
            best_score = score

    return best_date


def _to_date(value: object) -> Optional[date]:
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        return parsed.date()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.date()
        except ValueError:
            continue
    return None


def _week_of_month(value: date) -> int:
    return (value.day - 1) // 7 + 1


def _is_last_week_of_month(value: date) -> bool:
    days_in_month = monthrange(value.year, value.month)[1]
    return value.day > days_in_month - 7


def _next_month_reference(reference_day: date) -> Tuple[int, int]:
    if reference_day.month == 12:
        return reference_day.year + 1, 1
    return reference_day.year, reference_day.month + 1
