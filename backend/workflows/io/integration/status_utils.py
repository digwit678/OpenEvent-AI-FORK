"""
Status normalization utilities for Supabase integration.

The internal workflow uses capitalized status values (Lead, Option, Confirmed)
while Supabase uses lowercase (lead, option, confirmed).

This module provides bidirectional conversion.

Based on EMAIL_WORKFLOW_INTEGRATION_REQUIREMENTS.md Section A8.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional


# =============================================================================
# Event Status Mapping
# =============================================================================

class EventStatusInternal(str, Enum):
    """Internal event status values (capitalized)."""
    LEAD = "Lead"
    OPTION = "Option"
    CONFIRMED = "Confirmed"
    CANCELLED = "Cancelled"
    BLOCKED = "Blocked"


class EventStatusSupabase(str, Enum):
    """Supabase event status values (lowercase)."""
    LEAD = "lead"
    OPTION = "option"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


# Bidirectional mapping
_EVENT_STATUS_TO_SUPABASE = {
    "Lead": "lead",
    "lead": "lead",
    "LEAD": "lead",
    "Option": "option",
    "option": "option",
    "OPTION": "option",
    "Confirmed": "confirmed",
    "confirmed": "confirmed",
    "CONFIRMED": "confirmed",
    "Cancelled": "cancelled",
    "cancelled": "cancelled",
    "CANCELLED": "cancelled",
    "Blocked": "blocked",
    "blocked": "blocked",
    "BLOCKED": "blocked",
}

_EVENT_STATUS_TO_INTERNAL = {
    "lead": "Lead",
    "Lead": "Lead",
    "LEAD": "Lead",
    "option": "Option",
    "Option": "Option",
    "OPTION": "Option",
    "confirmed": "Confirmed",
    "Confirmed": "Confirmed",
    "CONFIRMED": "Confirmed",
    "cancelled": "Cancelled",
    "Cancelled": "Cancelled",
    "CANCELLED": "Cancelled",
    "blocked": "Blocked",
    "Blocked": "Blocked",
    "BLOCKED": "Blocked",
}


def event_status_to_supabase(status: Optional[str]) -> str:
    """
    Convert event status to Supabase format (lowercase).

    Args:
        status: Status value in any capitalization

    Returns:
        Lowercase status for Supabase

    Example:
        >>> event_status_to_supabase("Lead")
        'lead'
        >>> event_status_to_supabase("CONFIRMED")
        'confirmed'
    """
    if not status:
        return "lead"  # Default
    return _EVENT_STATUS_TO_SUPABASE.get(status, status.lower())


def event_status_to_internal(status: Optional[str]) -> str:
    """
    Convert event status to internal format (capitalized).

    Args:
        status: Status value in any capitalization

    Returns:
        Capitalized status for internal use

    Example:
        >>> event_status_to_internal("lead")
        'Lead'
        >>> event_status_to_internal("confirmed")
        'Confirmed'
    """
    if not status:
        return "Lead"  # Default
    return _EVENT_STATUS_TO_INTERNAL.get(status, status.capitalize())


# =============================================================================
# Client Status Mapping
# =============================================================================

class ClientStatusInternal(str, Enum):
    """Internal client status values."""
    LEAD = "Lead"
    OPTION = "Option"
    CONFIRMED = "Confirmed"
    CANCELLED = "Cancelled"


class ClientStatusSupabase(str, Enum):
    """Supabase client status values."""
    LEAD = "lead"
    OPTION = "option"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


# Use same mappings as event status
def client_status_to_supabase(status: Optional[str]) -> str:
    """Convert client status to Supabase format (lowercase)."""
    if not status:
        return "lead"
    return _EVENT_STATUS_TO_SUPABASE.get(status, status.lower())


def client_status_to_internal(status: Optional[str]) -> str:
    """Convert client status to internal format (capitalized)."""
    if not status:
        return "Lead"
    return _EVENT_STATUS_TO_INTERNAL.get(status, status.capitalize())


# =============================================================================
# Offer Status Mapping
# =============================================================================

class OfferStatusInternal(str, Enum):
    """Internal offer status values."""
    DRAFT = "Draft"
    SENT = "Sent"
    CONFIRMED = "Confirmed"
    CANCELLED = "Cancelled"


class OfferStatusSupabase(str, Enum):
    """Supabase offer status values."""
    DRAFT = "draft"
    SENT = "sent"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


_OFFER_STATUS_TO_SUPABASE = {
    "Draft": "draft",
    "draft": "draft",
    "DRAFT": "draft",
    "Sent": "sent",
    "sent": "sent",
    "SENT": "sent",
    "Confirmed": "confirmed",
    "confirmed": "confirmed",
    "CONFIRMED": "confirmed",
    "Cancelled": "cancelled",
    "cancelled": "cancelled",
    "CANCELLED": "cancelled",
}

_OFFER_STATUS_TO_INTERNAL = {
    "draft": "Draft",
    "Draft": "Draft",
    "DRAFT": "Draft",
    "sent": "Sent",
    "Sent": "Sent",
    "SENT": "Sent",
    "confirmed": "Confirmed",
    "Confirmed": "Confirmed",
    "CONFIRMED": "Confirmed",
    "cancelled": "Cancelled",
    "Cancelled": "Cancelled",
    "CANCELLED": "Cancelled",
}


def offer_status_to_supabase(status: Optional[str]) -> str:
    """Convert offer status to Supabase format (lowercase)."""
    if not status:
        return "draft"
    return _OFFER_STATUS_TO_SUPABASE.get(status, status.lower())


def offer_status_to_internal(status: Optional[str]) -> str:
    """Convert offer status to internal format (capitalized)."""
    if not status:
        return "Draft"
    return _OFFER_STATUS_TO_INTERNAL.get(status, status.capitalize())


# =============================================================================
# Task Status Mapping
# =============================================================================

class TaskStatusInternal(str, Enum):
    """Internal task status values."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


# Task statuses are already lowercase in both systems
def task_status_to_supabase(status: Optional[str]) -> str:
    """Convert task status to Supabase format."""
    if not status:
        return "pending"
    return status.lower().replace(" ", "_")


def task_status_to_internal(status: Optional[str]) -> str:
    """Convert task status to internal format."""
    if not status:
        return "pending"
    return status.lower().replace(" ", "_")


# =============================================================================
# Generic Status Converter
# =============================================================================

def normalize_status(
    status: Optional[str],
    entity_type: str,
    target: str = "supabase"
) -> str:
    """
    Generic status normalizer for any entity type.

    Args:
        status: Status value to convert
        entity_type: One of "event", "client", "offer", "task"
        target: "supabase" for lowercase, "internal" for capitalized

    Returns:
        Normalized status string

    Example:
        >>> normalize_status("Lead", "event", "supabase")
        'lead'
        >>> normalize_status("confirmed", "offer", "internal")
        'Confirmed'
    """
    if target == "supabase":
        converters = {
            "event": event_status_to_supabase,
            "events": event_status_to_supabase,
            "client": client_status_to_supabase,
            "clients": client_status_to_supabase,
            "offer": offer_status_to_supabase,
            "offers": offer_status_to_supabase,
            "task": task_status_to_supabase,
            "tasks": task_status_to_supabase,
        }
    else:
        converters = {
            "event": event_status_to_internal,
            "events": event_status_to_internal,
            "client": client_status_to_internal,
            "clients": client_status_to_internal,
            "offer": offer_status_to_internal,
            "offers": offer_status_to_internal,
            "task": task_status_to_internal,
            "tasks": task_status_to_internal,
        }

    converter = converters.get(entity_type.lower())
    if converter:
        return converter(status)

    # Fallback: just lowercase or capitalize
    if not status:
        return ""
    return status.lower() if target == "supabase" else status.capitalize()