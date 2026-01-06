#!/usr/bin/env python3
"""Generate future-valid calendar fixtures for room availability tests."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from services.rooms import load_room_catalog
from utils import json_io


def _build_busy_slots(start_from: datetime) -> List[Dict[str, str]]:
    base = start_from.replace(hour=0, minute=0, second=0, microsecond=0)
    slots = [
        (base + timedelta(days=30), 10, 14),
        (base + timedelta(days=45), 18, 22),
        (base + timedelta(days=75), 9, 12),
    ]
    entries: List[Dict[str, str]] = []
    for day, start_hour, end_hour in slots:
        start = day.replace(hour=start_hour, minute=0)
        end = day.replace(hour=end_hour, minute=0)
        entries.append(
            {
                "start": start.isoformat() + "Z",
                "end": end.isoformat() + "Z",
            }
        )
    return entries


def generate_calendar(fixtures_dir: Path) -> None:
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    catalog = load_room_catalog()
    base = datetime.utcnow()
    for record in catalog:
        calendar_id = record.calendar_id or record.room_id
        busy_slots = _build_busy_slots(base)
        payload = {"busy": busy_slots}
        target = fixtures_dir / f"{calendar_id}.json"
        with target.open("w", encoding="utf-8") as handle:
            json_io.dump(payload, handle, ensure_ascii=False, indent=2)
        print(f"wrote {target.relative_to(Path.cwd())}")


if __name__ == "__main__":
    calendar_dir = Path(__file__).resolve().parents[1] / "backend" / "adapters" / "calendar_data"
    generate_calendar(calendar_dir)
