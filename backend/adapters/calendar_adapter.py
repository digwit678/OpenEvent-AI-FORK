"""Adapters for reading calendar fixtures to support availability checks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


class CalendarAdapter:
    """Condition (purple): provide busy slot lookups for availability checks."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or Path(__file__).with_name("calendar_data")

    def get_busy(self, calendar_id: str, start_iso: str, end_iso: str) -> List[Dict[str, Any]]:
        """Return busy intervals as ISO strings from static fixtures."""

        if not calendar_id:
            return []
        if not self.data_dir.exists():
            return []
        candidate = self.data_dir / f"{calendar_id}.json"
        if not candidate.exists():
            return []
        try:
            with candidate.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except json.JSONDecodeError:
            return []
        intervals = payload.get("busy", [])
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
