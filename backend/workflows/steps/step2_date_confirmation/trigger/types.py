"""
Type definitions for Step2 Date Confirmation workflow.

Extracted from step2_handler.py for better modularity (D1 refactoring).

Usage:
    from backend.workflows.steps.step2_date_confirmation.trigger.types import (
        ConfirmationWindow,
        WindowHints,
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Tuple

# -----------------------------------------------------------------------------
# Core Types
# -----------------------------------------------------------------------------


@dataclass
class ConfirmationWindow:
    """Resolved confirmation payload for the requested event window."""

    display_date: str
    iso_date: str
    start_time: Optional[str]
    end_time: Optional[str]
    start_iso: Optional[str]
    end_iso: Optional[str]
    inherited_times: bool
    partial: bool
    source_message_id: Optional[str]


# Type alias for window hint tuples: (date_hint, time_hint, room_hint)
WindowHints = Tuple[Optional[str], Optional[Any], Optional[str]]

# -----------------------------------------------------------------------------
# Exports
# -----------------------------------------------------------------------------

__all__ = [
    "ConfirmationWindow",
    "WindowHints",
]
