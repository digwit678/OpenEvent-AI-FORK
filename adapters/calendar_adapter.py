"""Adapters for reading calendar fixtures to support availability checks.

The shared singleton can be reset in tests via `reset_calendar_adapter()`.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils import json_io

_CALENDAR_SINGLETON: Optional["CalendarAdapter"] = None


class CalendarAdapter:
    """Condition (purple): provide busy slot lookups for availability checks."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or Path(__file__).with_name("calendar_data")
        self._load_cached = lru_cache(maxsize=32)(self._load_calendar_unmemoized)

    def _load_calendar_unmemoized(self, calendar_id: str) -> Dict[str, Any]:
        if not calendar_id:
            return {"busy": []}
        if not self.data_dir.exists():
            return {"busy": []}
        candidate = self.data_dir / f"{calendar_id}.json"
        if not candidate.exists():
            return {"busy": []}
        try:
            with candidate.open("r", encoding="utf-8") as handle:
                payload = json_io.load(handle)
        except json.JSONDecodeError:  # type: ignore[name-defined]
            return {"busy": []}
        if "busy" not in payload or not isinstance(payload["busy"], list):
            payload["busy"] = []
        return payload

    def clear_cache(self) -> None:
        """Drop memoized calendar files (tests call this when mutating fixtures)."""

        self._load_cached.cache_clear()

    def get_busy(self, calendar_id: str, start_iso: str, end_iso: str) -> List[Dict[str, Any]]:
        """Return busy intervals as ISO strings from static fixtures."""

        payload = self._load_cached(calendar_id)
        intervals = payload.get("busy", []) if isinstance(payload, dict) else []
        cleaned: List[Dict[str, Any]] = []
        for item in intervals:
            start = item.get("start")
            end = item.get("end")
            if not start or not end:
                continue
            cleaned.append({"start": start, "end": end})
        return cleaned


def ensure_calendar_dir() -> None:
    """Utility to create the local calendar data directory when running scripts."""

    path = Path(__file__).with_name("calendar_data")
    path.mkdir(exist_ok=True)


def get_calendar_adapter(data_dir: Path | None = None) -> CalendarAdapter:
    """Return a shared calendar adapter instance (tests may pass a custom path)."""

    global _CALENDAR_SINGLETON
    if data_dir is not None:
        return CalendarAdapter(data_dir)
    if _CALENDAR_SINGLETON is None:
        _CALENDAR_SINGLETON = CalendarAdapter()
    return _CALENDAR_SINGLETON


def reset_calendar_adapter() -> None:
    """Reset the shared calendar adapter."""

    global _CALENDAR_SINGLETON
    if _CALENDAR_SINGLETON is not None:
        _CALENDAR_SINGLETON.clear_cache()
    _CALENDAR_SINGLETON = None
