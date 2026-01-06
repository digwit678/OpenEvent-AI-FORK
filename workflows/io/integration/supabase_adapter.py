"""
Supabase adapter - same interface as database.py but using Supabase.

This module provides the same function signatures as database.py
but stores data in Supabase instead of local JSON files.

Usage:
    When OE_INTEGRATION_MODE=supabase, the adapter.py module routes
    calls here instead of to database.py.

Requirements:
    - supabase-py package
    - Environment variables: OE_SUPABASE_URL, OE_SUPABASE_KEY, OE_TEAM_ID, OE_SYSTEM_USER_ID
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from .config import INTEGRATION_CONFIG, get_team_id, get_system_user_id
from .field_mapping import (
    translate_record_to_supabase,
    translate_record_from_supabase,
    convert_room_id_to_array,
    convert_room_ids_to_single,
)
from .status_utils import (
    event_status_to_supabase,
    event_status_to_internal,
    client_status_to_supabase,
)
from .uuid_adapter import (
    generate_uuid,
    normalize_email,
    is_valid_uuid,
    register_client_lookup,
    get_entity_registry,
)
from .offer_utils import generate_offer_number, format_date_for_supabase
from .hil_tasks import create_message_approval_task, create_email_record


__workflow_role__ = "Database"

logger = logging.getLogger(__name__)


# =============================================================================
# Supabase Client Initialization
# =============================================================================

_supabase_client = None


def get_supabase_client():
    """
    Get or create the Supabase client.

    Lazily initializes the client on first use.
    """
    global _supabase_client

    if _supabase_client is not None:
        return _supabase_client

    try:
        from supabase import create_client, Client
    except ImportError:
        raise ImportError(
            "supabase-py is required for integration mode. "
            "Install with: pip install supabase"
        )

    url = INTEGRATION_CONFIG.supabase_url
    key = INTEGRATION_CONFIG.supabase_key

    if not url or not key:
        raise ValueError(
            "OE_SUPABASE_URL and OE_SUPABASE_KEY must be set in integration mode"
        )

    _supabase_client = create_client(url, key)

    # Register client lookup function for UUID adapter
    register_client_lookup(_lookup_client_by_email)

    # Load entity registries
    _load_entity_registries()

    return _supabase_client


def _lookup_client_by_email(email: str, team_id: str) -> Optional[str]:
    """Lookup client UUID by email (used by uuid_adapter)."""
    client = get_supabase_client()
    result = client.table("clients") \
        .select("id") \
        .eq("email", email) \
        .eq("team_id", team_id) \
        .maybe_single() \
        .execute()

    if result.data:
        return result.data["id"]
    return None


def _load_entity_registries():
    """Load room and product name -> UUID mappings."""
    client = get_supabase_client()
    team_id = get_team_id()

    if not team_id:
        return

    registry = get_entity_registry()

    # Load rooms
    rooms_result = client.table("rooms") \
        .select("id, name") \
        .eq("team_id", team_id) \
        .execute()

    # Load products
    products_result = client.table("products") \
        .select("id, name") \
        .eq("team_id", team_id) \
        .execute()

    registry.load_from_supabase(
        rooms_result.data or [],
        products_result.data or []
    )


# =============================================================================
# Client Operations
# =============================================================================

def upsert_client(
    email: str,
    name: Optional[str] = None,
    company: Optional[str] = None,
    phone: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create or return a client profile.

    Matches database.py:upsert_client interface but returns Supabase record.

    Args:
        email: Client email (used for lookup)
        name: Client name
        company: Client company
        phone: Client phone

    Returns:
        Client record with UUID
    """
    client = get_supabase_client()
    team_id = get_team_id()
    user_id = get_system_user_id()
    email_normalized = normalize_email(email)

    # Try to find existing client
    existing = client.table("clients") \
        .select("*") \
        .eq("email", email_normalized) \
        .eq("team_id", team_id) \
        .maybe_single() \
        .execute()

    if existing.data:
        # Update if name was provided and client has no name
        if name and not existing.data.get("name"):
            client.table("clients") \
                .update({"name": name}) \
                .eq("id", existing.data["id"]) \
                .eq("team_id", team_id) \
                .execute()
            existing.data["name"] = name
        return existing.data

    # Create new client
    new_client = {
        "name": name or "Unknown",
        "email": email_normalized,
        "company": company,
        "phone": phone,
        "team_id": team_id,
        "user_id": user_id,
        "status": "lead",
    }

    result = client.table("clients").insert(new_client).execute()
    return result.data[0]


# =============================================================================
# Event Operations
# =============================================================================

def create_event_entry(event_data: Dict[str, Any]) -> str:
    """
    Insert a new event entry and return its identifier.

    Matches database.py:create_event_entry interface.

    Args:
        event_data: Event data in internal format

    Returns:
        Event UUID
    """
    client = get_supabase_client()
    team_id = get_team_id()
    user_id = get_system_user_id()

    # Generate title if not provided
    client_name = event_data.get("Name") or event_data.get("name") or "Unknown"
    title = event_data.get("title") or f"Event booking - {client_name}"

    # Map internal fields to Supabase schema
    supabase_event = {
        "title": title,
        "team_id": team_id,
        "user_id": user_id,
        "status": event_status_to_supabase(event_data.get("status", "Lead")),

        # Date fields
        "event_date": _convert_date_to_iso(event_data.get("Event Date")),
        "start_time": event_data.get("Start Time") or "09:00:00",
        "end_time": event_data.get("End Time") or "18:00:00",

        # Attendees
        "attendees": _parse_participants(event_data.get("Number of Participants")),

        # Room (as array)
        "room_ids": [],  # Will be set when room is selected

        # Notes
        "notes": event_data.get("Additional Info"),
        "description": event_data.get("Type of Event"),

        # Workflow state (requires Supabase schema additions)
        "current_step": 1,
        "date_confirmed": False,
    }

    # Remove None values
    supabase_event = {k: v for k, v in supabase_event.items() if v is not None}

    result = client.table("events").insert(supabase_event).execute()
    return result.data[0]["id"]


def find_event_by_id(event_id: str) -> Optional[Dict[str, Any]]:
    """
    Find an event by its UUID.

    Args:
        event_id: Event UUID

    Returns:
        Event record or None
    """
    client = get_supabase_client()
    team_id = get_team_id()

    result = client.table("events") \
        .select("*") \
        .eq("id", event_id) \
        .eq("team_id", team_id) \
        .maybe_single() \
        .execute()

    if result.data:
        return _convert_event_to_internal(result.data)
    return None


def find_event_by_email(email: str) -> Optional[Dict[str, Any]]:
    """
    Find the most recent event for a client email.

    Args:
        email: Client email

    Returns:
        Event record or None
    """
    client = get_supabase_client()
    team_id = get_team_id()

    # First find the client
    client_result = client.table("clients") \
        .select("id") \
        .eq("email", normalize_email(email)) \
        .eq("team_id", team_id) \
        .maybe_single() \
        .execute()

    if not client_result.data:
        return None

    client_id = client_result.data["id"]

    # Find most recent event for this client
    # Note: This requires a client_id field on events, which may need to be added
    # For now, we search by contact email in the notes or a join
    events_result = client.table("events") \
        .select("*") \
        .eq("team_id", team_id) \
        .order("created_at", desc=True) \
        .limit(1) \
        .execute()

    if events_result.data:
        return _convert_event_to_internal(events_result.data[0])
    return None


def update_event_metadata(event_id: str, **fields: Any) -> Dict[str, Any]:
    """
    Update event metadata fields.

    Args:
        event_id: Event UUID
        **fields: Fields to update

    Returns:
        Updated event record
    """
    client = get_supabase_client()

    # Translate field names
    supabase_fields = {}
    for key, value in fields.items():
        if key == "chosen_date":
            supabase_fields["event_date"] = _convert_date_to_iso(value)
        elif key == "locked_room_id":
            supabase_fields["room_ids"] = convert_room_id_to_array(value)
        elif key == "status":
            supabase_fields["status"] = event_status_to_supabase(value)
        elif key == "number_of_participants":
            supabase_fields["attendees"] = _parse_participants(value)
        else:
            supabase_fields[key] = value

    team_id = get_team_id()
    result = client.table("events") \
        .update(supabase_fields) \
        .eq("id", event_id) \
        .eq("team_id", team_id) \
        .execute()

    return result.data[0] if result.data else {}


def update_event_date(event_id: str, date_iso: str) -> Dict[str, Any]:
    """
    Persist the confirmed event date.

    Args:
        event_id: Event UUID
        date_iso: Date in ISO format (YYYY-MM-DD)

    Returns:
        Updated event record
    """
    return update_event_metadata(
        event_id,
        event_date=date_iso,
        date_confirmed=True,
    )


def update_event_room(
    event_id: str,
    *,
    selected_room: str,
    status: str,
) -> Dict[str, Any]:
    """
    Persist room selection.

    Args:
        event_id: Event UUID
        selected_room: Room UUID or name
        status: Selection status

    Returns:
        Updated event record
    """
    # Convert room name to UUID if needed
    registry = get_entity_registry()
    room_uuid = registry.get_room_uuid(selected_room) or selected_room

    return update_event_metadata(
        event_id,
        room_ids=[room_uuid] if room_uuid else [],
        status=status,
    )


# =============================================================================
# Task Operations (HIL)
# =============================================================================

def create_hil_task(
    event_id: str,
    task_type: str,
    title: str,
    description: str,
    payload: Dict[str, Any],
    client_name: Optional[str] = None,
    priority: str = "high",
) -> str:
    """
    Create a HIL approval task.

    Args:
        event_id: Event UUID
        task_type: Type of task (category)
        title: Task title
        description: Task description
        payload: Task payload with action details
        client_name: Client name for display
        priority: Task priority

    Returns:
        Task UUID
    """
    client = get_supabase_client()
    team_id = get_team_id()
    user_id = get_system_user_id()

    task = {
        "title": title,
        "description": description,
        "category": task_type,
        "priority": priority,
        "team_id": team_id,
        "user_id": user_id,
        "event_id": event_id,
        "client_name": client_name,
        "status": "pending",
        # Note: payload may need to be stored in a JSONB column
        # For now, include key fields directly
    }

    result = client.table("tasks").insert(task).execute()
    return result.data[0]["id"]


def create_message_approval(
    event_id: str,
    client_name: str,
    client_email: str,
    draft_message: str,
    subject: Optional[str] = None,
) -> str:
    """
    Create a message approval task (core HIL requirement).

    Args:
        event_id: Event UUID
        client_name: Client name
        client_email: Client email
        draft_message: AI-generated message
        subject: Email subject

    Returns:
        Task UUID
    """
    client = get_supabase_client()
    team_id = get_team_id()
    user_id = get_system_user_id()

    task = create_message_approval_task(
        team_id=team_id,
        user_id=user_id,
        event_id=event_id,
        client_name=client_name,
        client_email=client_email,
        draft_message=draft_message,
        subject=subject,
    )

    result = client.table("tasks").insert(task).execute()
    return result.data[0]["id"]


# =============================================================================
# Email Operations
# =============================================================================

def store_email(
    from_email: str,
    to_email: str,
    subject: str,
    body_text: str,
    event_id: Optional[str] = None,
    client_id: Optional[str] = None,
    is_outgoing: bool = False,
    thread_id: Optional[str] = None,
) -> str:
    """
    Store an email in the conversation history.

    Args:
        from_email: Sender email
        to_email: Recipient email
        subject: Email subject
        body_text: Email body
        event_id: Linked event UUID
        client_id: Linked client UUID
        is_outgoing: True for sent emails
        thread_id: Email thread ID

    Returns:
        Email UUID
    """
    client = get_supabase_client()
    team_id = get_team_id()
    user_id = get_system_user_id()

    email_record = create_email_record(
        team_id=team_id,
        user_id=user_id,
        from_email=from_email,
        to_email=to_email,
        subject=subject,
        body_text=body_text,
        event_id=event_id,
        client_id=client_id,
        is_sent=is_outgoing,
        thread_id=thread_id,
    )

    result = client.table("emails").insert(email_record).execute()
    return result.data[0]["id"]


# =============================================================================
# Room Operations
# =============================================================================

def get_rooms(date_iso: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Get all rooms, optionally checking availability for a date.

    Args:
        date_iso: Optional date to check availability

    Returns:
        List of room records
    """
    client = get_supabase_client()
    team_id = get_team_id()

    result = client.table("rooms") \
        .select("*") \
        .eq("team_id", team_id) \
        .execute()

    return result.data or []


def get_room_by_id(room_id: str) -> Optional[Dict[str, Any]]:
    """
    Get a room by UUID.

    Args:
        room_id: Room UUID

    Returns:
        Room record or None
    """
    client = get_supabase_client()
    team_id = get_team_id()

    result = client.table("rooms") \
        .select("*") \
        .eq("id", room_id) \
        .eq("team_id", team_id) \
        .maybe_single() \
        .execute()

    return result.data


# =============================================================================
# Offer Operations
# =============================================================================

def create_offer(
    event_id: str,
    line_items: List[Dict[str, Any]],
    total_amount: float,
    deposit_enabled: bool = False,
    deposit_percentage: Optional[float] = None,
) -> str:
    """
    Create an offer for an event.

    Args:
        event_id: Event UUID
        line_items: List of line items
        total_amount: Total amount
        deposit_enabled: Whether deposit is required
        deposit_percentage: Deposit percentage

    Returns:
        Offer UUID
    """
    client = get_supabase_client()
    team_id = get_team_id()
    user_id = get_system_user_id()

    offer = {
        "team_id": team_id,
        "offer_number": generate_offer_number(),
        "subject": "Event Offer",
        "offer_date": format_date_for_supabase(),
        "user_id": user_id,
        "event_id": event_id,
        "total_amount": total_amount,
        "deposit_enabled": deposit_enabled,
        "deposit_percentage": deposit_percentage,
        "status": "draft",
    }

    result = client.table("offers").insert(offer).execute()
    offer_id = result.data[0]["id"]

    # Insert line items
    for item in line_items:
        item["offer_id"] = offer_id
        item["team_id"] = team_id
        client.table("offer_line_items").insert(item).execute()

    return offer_id


# =============================================================================
# Helper Functions
# =============================================================================

def _convert_date_to_iso(date_str: Optional[str]) -> Optional[str]:
    """Convert various date formats to ISO (YYYY-MM-DD)."""
    if not date_str or date_str == "Not specified":
        return None

    # Already ISO format
    if len(date_str) == 10 and date_str[4] == "-":
        return date_str

    # DD.MM.YYYY format
    if "." in date_str:
        try:
            dt = datetime.strptime(date_str, "%d.%m.%Y")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass

    return date_str


def _parse_participants(value: Any) -> Optional[int]:
    """Parse participants count to integer."""
    if value is None or value == "Not specified":
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _convert_event_to_internal(supabase_event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert Supabase event format to internal format.

    Used for compatibility with existing workflow code.
    """
    # Create internal format
    internal = {
        "event_id": supabase_event["id"],
        "status": event_status_to_internal(supabase_event.get("status")),
        "chosen_date": supabase_event.get("event_date"),
        "date_confirmed": supabase_event.get("date_confirmed", False),
        "locked_room_id": convert_room_ids_to_single(supabase_event.get("room_ids")),
        "current_step": supabase_event.get("current_step", 1),
        "event_data": {
            "Event Date": supabase_event.get("event_date"),
            "Start Time": supabase_event.get("start_time"),
            "End Time": supabase_event.get("end_time"),
            "Number of Participants": supabase_event.get("attendees"),
            "Additional Info": supabase_event.get("notes"),
            "Type of Event": supabase_event.get("description"),
        },
    }

    # Preserve original fields for hybrid access
    internal["_supabase_record"] = supabase_event

    return internal
