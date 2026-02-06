"""
MODULE: workflows/notifications/__init__.py
PURPOSE: Client notification generation for manager-initiated actions.
"""

from .manager_action_drafts import (
    generate_date_change_notification,
    generate_room_change_notification,
    generate_room_cancellation_notification,
    generate_requirements_update_notification,
    generate_offer_update_notification,
    generate_site_visit_reschedule_notification,
)

__all__ = [
    "generate_date_change_notification",
    "generate_room_change_notification",
    "generate_room_cancellation_notification",
    "generate_requirements_update_notification",
    "generate_offer_update_notification",
    "generate_site_visit_reschedule_notification",
]
