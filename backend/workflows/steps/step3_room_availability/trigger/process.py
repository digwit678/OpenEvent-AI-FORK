"""
DEPRECATED: Import from step3_handler.py instead.

This module re-exports from the new filename for backwards compatibility.
"""

from .step3_handler import evaluate_room_statuses, process, handle_select_room_action, render_rooms_response

__all__ = ["evaluate_room_statuses", "process", "handle_select_room_action", "render_rooms_response"]
