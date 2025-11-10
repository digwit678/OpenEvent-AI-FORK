from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

ROOM_OUTCOME_AVAILABLE = "Available"
ROOM_OUTCOME_OPTION = "Option"
ROOM_OUTCOME_UNAVAILABLE = "Unavailable"


@dataclass
class RankedRoom:
    room: str
    status: str
    score: float
    hint: str
    capacity_ok: bool


def _config_by_name() -> Dict[str, Dict[str, object]]:
    from backend.workflows.groups.room_availability.db_pers import load_rooms_config

    rooms = load_rooms_config()
    return {str(entry.get("name")): entry for entry in rooms if entry.get("name")}


def _status_weight(status: str) -> int:
    lookup = {
        ROOM_OUTCOME_AVAILABLE: 60,
        ROOM_OUTCOME_OPTION: 35,
        ROOM_OUTCOME_UNAVAILABLE: 5,
    }
    return lookup.get(status, 0)


def _capacity_score(config: Dict[str, object], pax: Optional[int]) -> float:
    if pax is None:
        return 20.0
    capacity_min = config.get("capacity_min")
    capacity_max = config.get("capacity_max")
    if not isinstance(capacity_min, (int, float)) or not isinstance(capacity_max, (int, float)):
        return 15.0
    if capacity_min <= pax <= capacity_max:
        return 35.0
    if pax < capacity_min:
        return max(10.0 - (capacity_min - pax) * 0.5, 0)
    return max(5.0 - (pax - capacity_max) * 0.5, 0)


def _preference_score(features: Iterable[str], keywords: Iterable[str]) -> float:
    feature_lower = {str(item).lower() for item in features}
    score = 0.0
    for keyword in keywords:
        token = keyword.strip().lower()
        if not token:
            continue
        if token in feature_lower:
            score += 6.0
        else:
            for feature in feature_lower:
                if token in feature:
                    score += 4.0
                    break
    return score


def rank_rooms(
    status_map: Dict[str, str],
    *,
    preferred_room: Optional[str] = None,
    pax: Optional[int] = None,
    preferences: Optional[Dict[str, object]] = None,
) -> List[RankedRoom]:
    config_map = _config_by_name()
    preferred_lower = (preferred_room or "").strip().lower()
    wish_products = list((preferences or {}).get("wish_products") or []) if preferences else []
    keywords = list((preferences or {}).get("keywords") or []) if preferences else []
    hints_default = str((preferences or {}).get("default_hint") or "Products available")

    ranked: List[RankedRoom] = []

    for room, status in status_map.items():
        config = config_map.get(room, {})
        status_score = _status_weight(status)
        capacity_value = _capacity_score(config, pax)
        preference_value = _preference_score(config.get("features", []) or [], keywords)
        preferred_bonus = 10.0 if room.strip().lower() == preferred_lower else 0.0
        hint = wish_products[0] if wish_products else hints_default
        capacity_ok = capacity_value >= 30.0
        total = status_score + capacity_value + preference_value + preferred_bonus
        ranked.append(RankedRoom(room=room, status=status, score=total, hint=hint, capacity_ok=capacity_ok))

    ranked.sort(key=lambda entry: (-entry.score, entry.room))
    return ranked
