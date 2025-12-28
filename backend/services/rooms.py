from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.utils import json_io


@dataclass(frozen=True)
class RoomRecord:
    room_id: str
    name: str
    calendar_id: Optional[str]
    capacity_max: Optional[int]
    capacity_by_layout: Dict[str, int]
    features: List[str]
    buffer_before_min: int
    buffer_after_min: int

    def matches_identifier(self, identifier: str) -> bool:
        lowered = identifier.strip().lower()
        return lowered in {
            self.room_id.lower(),
            self.name.lower(),
        }


def _normalize_features(features: Any) -> List[str]:
    if not features:
        return []
    items = features if isinstance(features, list) else [features]
    cleaned: List[str] = []
    for entry in items:
        text = str(entry or "").strip().lower()
        if not text:
            continue
        cleaned.append(text)
    return cleaned


def _normalize_capacity(payload: Any) -> Dict[str, int]:
    if not isinstance(payload, dict):
        return {}
    normalised: Dict[str, int] = {}
    for key, value in payload.items():
        try:
            qty = int(value)
        except (TypeError, ValueError):
            continue
        normalised[str(key).strip().lower().replace(" ", "_")] = qty
    return normalised


@lru_cache(maxsize=1)
def load_room_catalog(path: Optional[Path] = None) -> List[RoomRecord]:
    """Load the detailed room catalog from seed data."""

    rooms_path = path or Path(__file__).resolve().parents[1] / "data" / "rooms.json"
    if not rooms_path.exists():
        return []
    with rooms_path.open("r", encoding="utf-8") as handle:
        payload = json_io.load(handle)
    rooms_data = payload.get("rooms") if isinstance(payload, dict) else None
    if not isinstance(rooms_data, list):
        return []

    catalog: List[RoomRecord] = []
    for entry in rooms_data:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        room_id = str(entry.get("id") or name).strip()
        if not name:
            continue
        record = RoomRecord(
            room_id=room_id or name,
            name=name,
            calendar_id=entry.get("calendar_id"),
            capacity_max=_safe_int(entry.get("capacity_max")),
            capacity_by_layout=_normalize_capacity(entry.get("capacity_by_layout")),
            features=_normalize_features(entry.get("features")),
            buffer_before_min=_safe_int(entry.get("buffer_before_min"), default=30),
            buffer_after_min=_safe_int(entry.get("buffer_after_min"), default=30),
        )
        catalog.append(record)
    return catalog


def get_room(identifier: str) -> Optional[RoomRecord]:
    for record in load_room_catalog():
        if record.matches_identifier(identifier):
            return record
    return None


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default