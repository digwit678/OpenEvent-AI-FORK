from __future__ import annotations

from datetime import date, datetime
from typing import Optional


def format_ts_to_ddmmyyyy(ts_str: Optional[str]) -> str:
    """[Condition] Convert an ISO timestamp to DD.MM.YYYY with graceful fallback."""

    if not ts_str:
        return date.today().strftime("%d.%m.%Y")
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except ValueError:
        return date.today().strftime("%d.%m.%Y")
    return dt.strftime("%d.%m.%Y")


def format_iso_date_to_ddmmyyyy(iso_date: Optional[str]) -> Optional[str]:
    """[Condition] Convert an ISO YYYY-MM-DD date value into DD.MM.YYYY."""

    if not iso_date:
        return None
    try:
        dt = datetime.fromisoformat(iso_date)
    except ValueError:
        return None
    return dt.strftime("%d.%m.%Y")


def parse_ddmmyyyy(value: str) -> Optional[date]:
    """[Condition] Parse DD.MM.YYYY text into a date object if valid."""

    try:
        return datetime.strptime(value, "%d.%m.%Y").date()
    except ValueError:
        return None
