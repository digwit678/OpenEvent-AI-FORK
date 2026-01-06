from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from workflows.steps.step3_room_availability.db_pers import load_rooms_config

_STATUS_WEIGHTS = {
    "available": 2,
    "option": 1,
}

_COFFEE_TOKENS = {"coffee service", "coffee", "coffee & tea", "coffee/tea"}


@dataclass
class RoomProfile:
    room: str
    status: str
    date_score: int
    coffee_badge: str
    coffee_score: int
    coffee_available: bool
    requirements_badges: Dict[str, str]
    requirements_score: float
    capacity_badge: str
    capacity_fit: int
    capacity: Optional[int]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "room": self.room,
            "status": self.status,
            "date_score": self.date_score,
            "coffee_badge": self.coffee_badge,
            "coffee_score": self.coffee_score,
            "coffee_available": self.coffee_available,
            "requirements_badges": dict(self.requirements_badges),
            "requirements_score": self.requirements_score,
            "capacity_badge": self.capacity_badge,
            "capacity_fit": self.capacity_fit,
            "capacity": self.capacity,
        }


def rank(
    date_iso: Optional[str],
    pax: Optional[int],
    *,
    status_map: Dict[str, str],
    needs_catering: Optional[Sequence[str]] = None,
    needs_products: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """Compute deterministic room rankings with badges for downstream rendering."""

    config_map = _config_by_name()
    requested_coffee = _has_coffee_request(needs_catering)
    requested_products = _normalise_products(needs_products)

    profiles: List[RoomProfile] = []
    for room, status in status_map.items():
        config = config_map.get(room, {})
        normalized_status = str(status).strip().lower()
        date_score = _STATUS_WEIGHTS.get(normalized_status, 0)
        capacity_value = _room_capacity(config)
        capacity_fit_flag = 1 if pax is None or (capacity_value is not None and capacity_value >= pax) else 0
        capacity_badge = "✓" if capacity_fit_flag else "✗"

        coffee_available = _supports_coffee(config)
        coffee_badge = "✓" if coffee_available else "✗"
        coffee_score = 1 if coffee_available else 0

        requirements_badges, requirements_score = _requirements_badges(config, requested_products, pax)

        profile = RoomProfile(
            room=room,
            status=status,
            date_score=date_score,
            coffee_badge=coffee_badge,
            coffee_score=coffee_score,
            coffee_available=coffee_available,
            requirements_badges=requirements_badges,
            requirements_score=requirements_score,
            capacity_badge=capacity_badge,
            capacity_fit=capacity_fit_flag,
            capacity=capacity_value,
        )
        profiles.append(profile)

    profiles.sort(
        key=lambda entry: (
            -entry.date_score,
            -entry.coffee_score,
            -entry.requirements_score,
            -entry.capacity_fit,
            entry.room,
        )
    )
    return [profile.to_dict() for profile in profiles]


def _config_by_name() -> Dict[str, Dict[str, Any]]:
    rooms = load_rooms_config() or []
    return {str(room.get("name")): room for room in rooms if room.get("name")}


def _has_coffee_request(needs_catering: Optional[Sequence[str]]) -> bool:
    if not needs_catering:
        return False
    for token in needs_catering:
        if str(token).strip().lower() in _COFFEE_TOKENS:
            return True
    return False


def _normalise_products(needs_products: Optional[Sequence[str]]) -> List[str]:
    if not needs_products:
        return []
    normalised: List[str] = []
    for token in needs_products:
        cleaned = str(token).strip().lower()
        if not cleaned:
            continue
        normalised.append(cleaned)
    return normalised


def _room_capacity(config: Dict[str, Any]) -> Optional[int]:
    capacity = config.get("capacity_max") or config.get("capacity") or config.get("max_capacity")
    if capacity is None:
        return None
    try:
        return int(capacity)
    except (TypeError, ValueError):
        return None


def _supports_coffee(config: Dict[str, Any]) -> bool:
    services = _lower_tokens(config.get("services"))
    features = _lower_tokens(config.get("features"))
    return any("coffee" in token for token in services or features)


def _requirements_badges(
    config: Dict[str, Any],
    requested_products: Sequence[str],
    pax: Optional[int],
) -> Tuple[Dict[str, str], float]:
    badges: Dict[str, str] = {}
    score = 0.0
    for product in requested_products:
        product_lower = product.lower().strip()
        if product_lower in {"u-shape", "u_shape", "ushape"}:
            badge, value = _u_shape_badge(config, pax)
        elif product_lower in {"projector", "projection", "beamer"}:
            badge, value = _projector_badge(config)
        elif product_lower in {"flipchart", "flip chart", "flip charts", "flipcharts"}:
            badge, value = _flipchart_badge(config)
        elif product_lower in {"whiteboard", "white board", "whiteboards"}:
            badge, value = _whiteboard_badge(config)
        elif product_lower in {"microphone", "mic", "microphones", "mics"}:
            badge, value = _microphone_badge(config)
        else:
            # Generic fallback - check features and equipment
            badge, value = _generic_item_badge(config, product)
        badges[_canonical_product_key(product)] = badge
        score += value
    return badges, score


def _u_shape_badge(config: Dict[str, Any], pax: Optional[int]) -> Tuple[str, float]:
    layout_map = config.get("capacity_by_layout") or {}
    capacity = None
    for key in ("u_shape", "u-shape", "ushape"):
        if key in layout_map:
            capacity = layout_map[key]
            break
    if capacity is None:
        return "✗", 0.0
    try:
        capacity_value = int(capacity)
    except (TypeError, ValueError):
        capacity_value = None
    if pax is None or capacity_value is None:
        return "✓", 1.0
    if capacity_value >= pax:
        return "✓", 1.0
    return "~", 0.5


def _get_all_room_items(config: Dict[str, Any]) -> List[str]:
    """
    Get ALL items available in a room (both included and optional).

    Combines 'features' and 'equipment' from room config into a single
    searchable list of lowercase tokens.

    Note: The data model uses 'features' and 'equipment' historically.
    This function abstracts that into "all available items" for simpler logic.
    """
    room_amenities = _lower_tokens(config.get("features"))
    room_technical_gear = _lower_tokens(config.get("equipment"))
    return room_amenities + room_technical_gear


def _projector_badge(config: Dict[str, Any]) -> Tuple[str, float]:
    """Check if room has projector/beamer available."""
    available_in_room = _get_all_room_items(config)
    if any(token in {"projector", "beamer"} for token in available_in_room):
        return "✓", 1.0
    if "screen" in available_in_room or "projection" in available_in_room:
        return "~", 0.5
    return "✗", 0.0


def _flipchart_badge(config: Dict[str, Any]) -> Tuple[str, float]:
    """Check if room has flipchart available."""
    available_in_room = _get_all_room_items(config)
    # Match various spellings: "flip chart", "flipchart", "flip charts"
    has_flipchart = any("flip" in token and "chart" in token for token in available_in_room)
    if has_flipchart:
        return "✓", 1.0
    # Whiteboard as partial alternative
    has_whiteboard = any("whiteboard" in token or "white board" in token for token in available_in_room)
    if has_whiteboard:
        return "~", 0.5
    return "✗", 0.0


def _whiteboard_badge(config: Dict[str, Any]) -> Tuple[str, float]:
    """Check if room has whiteboard available."""
    available_in_room = _get_all_room_items(config)
    has_whiteboard = any("whiteboard" in token or "white board" in token for token in available_in_room)
    if has_whiteboard:
        return "✓", 1.0
    # Flipchart as partial alternative
    has_flipchart = any("flip" in token and "chart" in token for token in available_in_room)
    if has_flipchart:
        return "~", 0.5
    return "✗", 0.0


def _microphone_badge(config: Dict[str, Any]) -> Tuple[str, float]:
    """Check if room has microphone available."""
    available_in_room = _get_all_room_items(config)
    has_mic = any("microphone" in token or "mic" in token for token in available_in_room)
    if has_mic:
        return "✓", 1.0
    has_sound_system = any("sound system" in token or "sound_system" in token for token in available_in_room)
    if has_sound_system:
        return "~", 0.5
    return "✗", 0.0


def _generic_item_badge(config: Dict[str, Any], requested_item: str) -> Tuple[str, float]:
    """
    Generic check for any item requested by client.

    Returns:
        "✓" (1.0) - Item found in room (exact match)
        "~" (0.5) - Partial match (item name is substring of available item)
        "✗" (0.0) - Item not available in room
    """
    available_in_room = _get_all_room_items(config)
    requested_item_lower = requested_item.lower().strip()

    # Exact match in available items
    if requested_item_lower in available_in_room:
        return "✓", 1.0

    # Partial match (requested item is substring of any available item)
    for available_item in available_in_room:
        if requested_item_lower in available_item:
            return "~", 0.5

    # Not available
    return "✗", 0.0


def _lower_tokens(values: Optional[Iterable[Any]]) -> List[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    tokens: List[str] = []
    for value in values:
        if value is None:
            continue
        tokens.append(str(value).strip().lower())
    return tokens


def _canonical_product_key(product: str) -> str:
    """Normalize product names to canonical keys for consistent badge lookup."""
    token = str(product).strip().lower()
    if token in {"u_shape", "u-shape", "ushape"}:
        return "u-shape"
    if token in {"projector", "projection", "beamer"}:
        return "projector"
    if token in {"flipchart", "flip chart", "flip charts", "flipcharts"}:
        return "flipchart"
    if token in {"whiteboard", "white board", "whiteboards"}:
        return "whiteboard"
    if token in {"microphone", "mic", "microphones", "mics"}:
        return "microphone"
    return token


def get_max_capacity() -> int:
    """Return the maximum capacity across all configured rooms."""
    config_map = _config_by_name()
    max_cap = 0
    for config in config_map.values():
        cap = _room_capacity(config)
        if cap is not None and cap > max_cap:
            max_cap = cap
    return max_cap


def any_room_fits_capacity(pax: int) -> bool:
    """Check if any configured room can accommodate the given number of guests."""
    if pax is None or pax <= 0:
        return True
    config_map = _config_by_name()
    for config in config_map.values():
        cap = _room_capacity(config)
        if cap is not None and cap >= pax:
            return True
    return False


def filter_rooms_by_capacity(
    profiles: List[Dict[str, Any]],
    pax: Optional[int],
    *,
    include_close_matches: bool = True,
    close_match_threshold: float = 0.8,
) -> List[Dict[str, Any]]:
    """
    Filter room profiles to only include rooms that fit the capacity.

    Args:
        profiles: List of room profile dicts from rank()
        pax: Required capacity
        include_close_matches: If True, include rooms within threshold of capacity
        close_match_threshold: Rooms with capacity >= pax * threshold are "close"

    Returns:
        Filtered list of profiles. If none fit exactly, returns close matches.
        If none are close, returns empty list.
    """
    if pax is None or pax <= 0:
        return profiles

    exact_fits = [p for p in profiles if p.get("capacity_fit", 0) == 1]
    if exact_fits:
        return exact_fits

    if include_close_matches:
        threshold = int(pax * close_match_threshold)
        close_matches = [
            p for p in profiles
            if p.get("capacity") is not None and p["capacity"] >= threshold
        ]
        if close_matches:
            return close_matches

    return []
