"""
Field mapping utilities for schema translation.

Translates between internal workflow schema and Supabase schema.
This allows the workflow to use its internal naming while the
integration layer handles the translation to Supabase column names.

Based on EMAIL_WORKFLOW_INTEGRATION_REQUIREMENTS.md Section A1.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


# =============================================================================
# Column Name Mappings (Internal -> Supabase)
# =============================================================================

# Client table mappings
CLIENT_FIELD_MAP = {
    # internal_name: supabase_column
    "organization": "company",
    "org": "company",
    "Company": "company",
}

# Event table mappings
EVENT_FIELD_MAP = {
    # internal_name: supabase_column
    "chosen_date": "event_date",
    "Event Date": "event_date",
    "number_of_participants": "attendees",
    "Number of Participants": "attendees",
    "participants": "attendees",
    "locked_room_id": "room_ids",  # Note: also needs array conversion
    "capacity_max": "capacity",
}

# Task table mappings
TASK_FIELD_MAP = {
    "type": "category",
    "resolved_at": "completed_at",
}

# Offer table mappings
OFFER_FIELD_MAP = {
    "deposit_paid": "deposit_paid_at",  # Note: boolean -> timestamp check
    "deposit_status": "payment_status",
    "accepted_at": "confirmed_at",
}

# Room table mappings
ROOM_FIELD_MAP = {
    "capacity_max": "capacity",
}


# =============================================================================
# Layout Capacity Mappings
# =============================================================================

# Maps internal layout names to Supabase column names
LAYOUT_CAPACITY_MAP = {
    "theatre": "theater_capacity",
    "theater": "theater_capacity",
    "cocktail": "cocktail_capacity",
    "dinner": "seated_dinner_capacity",
    "seated": "seated_dinner_capacity",
    "seated_dinner": "seated_dinner_capacity",
    "standing": "standing_capacity",
}


# =============================================================================
# Reverse Mappings (Supabase -> Internal)
# =============================================================================

def _invert_map(mapping: Dict[str, str]) -> Dict[str, str]:
    """Create reverse mapping (may have collisions, takes first)."""
    return {v: k for k, v in mapping.items()}


CLIENT_FIELD_MAP_REVERSE = _invert_map(CLIENT_FIELD_MAP)
EVENT_FIELD_MAP_REVERSE = _invert_map(EVENT_FIELD_MAP)
TASK_FIELD_MAP_REVERSE = _invert_map(TASK_FIELD_MAP)
OFFER_FIELD_MAP_REVERSE = _invert_map(OFFER_FIELD_MAP)


# =============================================================================
# Translation Functions
# =============================================================================

def to_supabase_field(table: str, internal_field: str) -> str:
    """
    Translate an internal field name to Supabase column name.

    Args:
        table: Table name (clients, events, tasks, offers, rooms)
        internal_field: Internal field name used in workflow

    Returns:
        Supabase column name (or original if no mapping exists)

    Example:
        >>> to_supabase_field("events", "chosen_date")
        'event_date'
        >>> to_supabase_field("clients", "organization")
        'company'
    """
    mapping = {
        "clients": CLIENT_FIELD_MAP,
        "events": EVENT_FIELD_MAP,
        "tasks": TASK_FIELD_MAP,
        "offers": OFFER_FIELD_MAP,
        "rooms": ROOM_FIELD_MAP,
    }.get(table, {})

    return mapping.get(internal_field, internal_field)


def from_supabase_field(table: str, supabase_field: str) -> str:
    """
    Translate a Supabase column name to internal field name.

    Args:
        table: Table name
        supabase_field: Supabase column name

    Returns:
        Internal field name (or original if no mapping exists)
    """
    mapping = {
        "clients": CLIENT_FIELD_MAP_REVERSE,
        "events": EVENT_FIELD_MAP_REVERSE,
        "tasks": TASK_FIELD_MAP_REVERSE,
        "offers": OFFER_FIELD_MAP_REVERSE,
    }.get(table, {})

    return mapping.get(supabase_field, supabase_field)


def translate_record_to_supabase(table: str, record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Translate an entire record from internal schema to Supabase schema.

    Args:
        table: Table name
        record: Dictionary with internal field names

    Returns:
        Dictionary with Supabase column names

    Example:
        >>> translate_record_to_supabase("events", {
        ...     "chosen_date": "2025-02-15",
        ...     "number_of_participants": 50
        ... })
        {'event_date': '2025-02-15', 'attendees': 50}
    """
    return {
        to_supabase_field(table, k): v
        for k, v in record.items()
    }


def translate_record_from_supabase(table: str, record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Translate an entire record from Supabase schema to internal schema.

    Args:
        table: Table name
        record: Dictionary with Supabase column names

    Returns:
        Dictionary with internal field names
    """
    return {
        from_supabase_field(table, k): v
        for k, v in record.items()
    }


# =============================================================================
# Special Conversions
# =============================================================================

def convert_room_id_to_array(room_id: Optional[str]) -> list:
    """
    Convert single room_id string to room_ids array format.

    Supabase uses room_ids (array) instead of locked_room_id (string).

    Args:
        room_id: Single room ID string or None

    Returns:
        List containing the room_id, or empty list

    Example:
        >>> convert_room_id_to_array("uuid-123")
        ['uuid-123']
        >>> convert_room_id_to_array(None)
        []
    """
    if room_id is None:
        return []
    return [room_id]


def convert_room_ids_to_single(room_ids: Optional[list]) -> Optional[str]:
    """
    Convert room_ids array back to single room_id string.

    Args:
        room_ids: List of room IDs

    Returns:
        First room ID or None if empty
    """
    if not room_ids:
        return None
    return room_ids[0]


def convert_features_to_amenities(features: Dict[str, Any], equipment: Dict[str, Any] = None) -> list:
    """
    Convert features/equipment JSONB to amenities string array.

    Internal format:
        features = {"stage": True, "parking": True}
        equipment = {"projector": True, "flip_chart": 2}

    Supabase format:
        amenities = ["stage", "parking", "projector", "flip_chart"]

    Args:
        features: Features dictionary with boolean values
        equipment: Equipment dictionary with boolean/int values

    Returns:
        Flat list of amenity strings
    """
    amenities = []

    if features:
        for key, value in features.items():
            if value:  # Truthy check
                amenities.append(key)

    if equipment:
        for key, value in equipment.items():
            if value:  # Truthy check
                amenities.append(key)

    return amenities


def get_layout_capacity(room: Dict[str, Any], layout: Optional[str] = None) -> int:
    """
    Get room capacity for a specific layout.

    Handles both internal (layouts dict) and Supabase (separate columns) formats.

    Args:
        room: Room record
        layout: Layout name (theatre, cocktail, dinner, standing)

    Returns:
        Capacity for the layout, or general capacity as fallback
    """
    if layout:
        layout_lower = layout.lower()

        # Check Supabase format (separate columns)
        supabase_col = LAYOUT_CAPACITY_MAP.get(layout_lower)
        if supabase_col and room.get(supabase_col):
            return room[supabase_col]

        # Check internal format (layouts dict)
        layouts = room.get("layouts", {})
        if layouts.get(layout_lower):
            return layouts[layout_lower]

    # Fallback to general capacity
    return room.get("capacity") or room.get("capacity_max", 0)


def check_deposit_paid(offer: Dict[str, Any]) -> bool:
    """
    Check if deposit is paid, handling both formats.

    Internal: deposit_paid (boolean)
    Supabase: deposit_paid_at (timestamp, null = unpaid)

    Args:
        offer: Offer record

    Returns:
        True if deposit is paid
    """
    # Check Supabase format first
    if "deposit_paid_at" in offer:
        return offer["deposit_paid_at"] is not None

    # Check internal format
    return bool(offer.get("deposit_paid", False))
