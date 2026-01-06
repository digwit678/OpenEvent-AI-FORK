"""
DEPRECATED: Import from workflows.nlu or backend.detection.qna.general_qna instead.

This module provides backwards-compatible re-exports for tests and code that
still import from this old location.
"""

from detection.qna.general_qna import (
    detect_general_room_query,
    empty_general_qna_detection,
    quick_general_qna_scan,
    reset_general_qna_cache,
)

__all__ = [
    "detect_general_room_query",
    "empty_general_qna_detection",
    "quick_general_qna_scan",
    "reset_general_qna_cache",
]
