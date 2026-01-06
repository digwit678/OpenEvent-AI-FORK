"""
DEPRECATED: Import from step2_handler.py instead.

This module re-exports from the new filename for backwards compatibility.
"""

from .step2_handler import (
    process,
    ConfirmationWindow,
    _finalize_confirmation,
    _resolve_confirmation_window,
    _present_candidate_dates,
    _present_general_room_qna,
    _candidate_dates_for_constraints,
)
from workflows.qna.extraction import ensure_qna_extraction

__all__ = [
    "process",
    "ConfirmationWindow",
    "_finalize_confirmation",
    "_resolve_confirmation_window",
    "_present_candidate_dates",
    "_present_general_room_qna",
    "_candidate_dates_for_constraints",
    "ensure_qna_extraction",
]
