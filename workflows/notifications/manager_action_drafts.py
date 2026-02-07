"""
MODULE: workflows/notifications/manager_action_drafts.py
PURPOSE: Generate client-facing notification drafts for manager-initiated actions.

When a manager action affects a client's booking, these functions generate
professional, friendly notification drafts that go to the HIL queue for
manager approval before being sent to the client.

DESIGN PRINCIPLES:
- Clear and professional tone
- Explain what changed and why (if appropriate)
- Always offer next steps or contact options
- Draft format allows manager to edit before sending
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional


def _format_date(date_str: Optional[str]) -> str:
    """Format a date string for display."""
    if not date_str:
        return "not specified"

    try:
        # Try ISO format first
        if "T" in date_str:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return dt.strftime("%B %d, %Y")
        # Try YYYY-MM-DD
        elif "-" in date_str and len(date_str) == 10:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            return dt.strftime("%B %d, %Y")
        # Try DD.MM.YYYY
        elif "." in date_str:
            dt = datetime.strptime(date_str, "%d.%m.%Y")
            return dt.strftime("%B %d, %Y")
        else:
            return date_str
    except (ValueError, TypeError):
        return date_str or "not specified"


def _get_client_name(event_entry: Dict[str, Any]) -> str:
    """Extract client name from event entry."""
    event_data = event_entry.get("event_data") or {}
    name = event_data.get("Name") or event_data.get("name") or ""
    if not name:
        # Fall back to email
        email = event_data.get("Email") or event_data.get("email") or ""
        if email:
            name = email.split("@")[0].replace(".", " ").title()
    return name or "valued client"


def generate_date_change_notification(
    event_entry: Dict[str, Any],
    old_date: Optional[str],
    new_date: str,
) -> str:
    """
    Generate client-facing message about manager-initiated date change.

    This draft goes to the HIL queue for manager review before sending.
    """
    client_name = _get_client_name(event_entry)
    old_formatted = _format_date(old_date)
    new_formatted = _format_date(new_date)

    if old_date:
        return f"""Dear {client_name},

We wanted to let you know that your event date has been updated.

**Previous date:** {old_formatted}
**New date:** {new_formatted}

Please confirm that this new date works for you, or let us know if you'd like to discuss alternatives.

Best regards,
The OpenEvent Team"""
    else:
        return f"""Dear {client_name},

We have scheduled your event for {new_formatted}.

Please confirm that this date works for you, or let us know if you'd prefer a different date.

Best regards,
The OpenEvent Team"""


def generate_room_change_notification(
    event_entry: Dict[str, Any],
    old_room: Optional[str],
    new_room: str,
) -> str:
    """
    Generate client-facing message about manager-initiated room change.
    """
    client_name = _get_client_name(event_entry)

    if old_room:
        return f"""Dear {client_name},

We wanted to inform you that we've updated your room assignment.

**Previous room:** {old_room}
**New room:** {new_room}

This change was made to better accommodate your event requirements. If you have any questions about the new room or would like to discuss alternatives, please let us know.

Best regards,
The OpenEvent Team"""
    else:
        return f"""Dear {client_name},

Great news! We've reserved {new_room} for your event.

If you'd like more information about the room or would prefer a different option, please let us know.

Best regards,
The OpenEvent Team"""


def generate_room_cancellation_notification(
    event_entry: Dict[str, Any],
    cancelled_room: str,
    reason: Optional[str],
) -> str:
    """
    Generate client-facing message about manager-initiated room cancellation.
    """
    client_name = _get_client_name(event_entry)

    reason_text = ""
    if reason:
        reason_text = f"\n\n{reason}\n"

    return f"""Dear {client_name},

We need to inform you that the room reservation for {cancelled_room} has been cancelled.{reason_text}

We apologize for any inconvenience this may cause. Our team is ready to help you find an alternative room that meets your needs.

Please let us know your preferences, and we'll work to find the best available option for your event.

Best regards,
The OpenEvent Team"""


def generate_requirements_update_notification(
    event_entry: Dict[str, Any],
    old_requirements: Dict[str, Any],
    new_requirements: Dict[str, Any],
) -> str:
    """
    Generate client-facing message about manager-initiated requirements update.
    """
    client_name = _get_client_name(event_entry)

    # Build list of changes
    changes = []

    old_participants = old_requirements.get("number_of_participants")
    new_participants = new_requirements.get("number_of_participants")
    if old_participants != new_participants and new_participants:
        changes.append(f"- Number of guests: {new_participants}")

    old_layout = old_requirements.get("seating_layout")
    new_layout = new_requirements.get("seating_layout")
    if old_layout != new_layout and new_layout:
        changes.append(f"- Room setup: {new_layout}")

    old_special = old_requirements.get("special_requirements")
    new_special = new_requirements.get("special_requirements")
    if old_special != new_special and new_special:
        changes.append(f"- Special requirements: {new_special}")

    changes_text = "\n".join(changes) if changes else "- Event requirements have been updated"

    return f"""Dear {client_name},

We've updated your event requirements based on our records:

{changes_text}

Please confirm these details are correct, or let us know if any adjustments are needed.

Best regards,
The OpenEvent Team"""


def generate_offer_update_notification(
    event_entry: Dict[str, Any],
    old_offer: Dict[str, Any],
    new_offer: Dict[str, Any],
) -> str:
    """
    Generate client-facing message about manager-initiated offer update.
    """
    client_name = _get_client_name(event_entry)

    # Build change description
    changes = []

    old_total = old_offer.get("total")
    new_total = new_offer.get("total")
    if old_total != new_total and new_total:
        changes.append(f"- Updated pricing: CHF {new_total}")

    old_discount = old_offer.get("discount")
    new_discount = new_offer.get("discount")
    if old_discount != new_discount and new_discount:
        changes.append(f"- Applied discount: {new_discount}%")

    old_terms = old_offer.get("terms")
    new_terms = new_offer.get("terms")
    if old_terms != new_terms and new_terms:
        changes.append(f"- Updated terms: {new_terms}")

    changes_text = "\n".join(changes) if changes else "- The offer has been updated"

    return f"""Dear {client_name},

We've updated your event offer:

{changes_text}

A revised offer document will be prepared for your review. Please let us know if you have any questions.

Best regards,
The OpenEvent Team"""


def generate_site_visit_reschedule_notification(
    event_entry: Dict[str, Any],
    old_date: Optional[str],
    old_time: Optional[str],
    new_date: Optional[str],
    new_time: Optional[str],
) -> str:
    """
    Generate client-facing message about manager-initiated site visit reschedule.
    """
    client_name = _get_client_name(event_entry)

    old_formatted = _format_date(old_date)
    new_formatted = _format_date(new_date) if new_date else old_formatted

    old_datetime = f"{old_formatted} at {old_time}" if old_time else old_formatted
    new_datetime = f"{new_formatted} at {new_time}" if new_time else new_formatted

    if old_date or old_time:
        return f"""Dear {client_name},

Your site visit has been rescheduled.

**Previous:** {old_datetime}
**New:** {new_datetime}

Please confirm this new time works for you. If you need to reschedule again, just let us know and we'll find another suitable time.

Best regards,
The OpenEvent Team"""
    else:
        return f"""Dear {client_name},

We've scheduled your site visit for {new_datetime}.

Please confirm this time works for you, or let us know if you'd prefer a different time slot.

We look forward to showing you our venue!

Best regards,
The OpenEvent Team"""


__all__ = [
    "generate_date_change_notification",
    "generate_room_change_notification",
    "generate_room_cancellation_notification",
    "generate_requirements_update_notification",
    "generate_offer_update_notification",
    "generate_site_visit_reschedule_notification",
]
