"""
DEPRECATED: Import from backend.detection.intent instead.

This module provides backwards-compatible re-exports for tests and code that
still import from this old location.
"""

from backend.detection.intent import (
    classify_intent,
    spans_multiple_steps,
    get_qna_steps,
    is_action_request,
    QNA_TYPE_TO_STEP,
    _detect_qna_types,
    _looks_like_manager_request,
    _RESUME_PHRASES,
    # Confidence exports
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_LOW,
    CONFIDENCE_NONSENSE,
    confidence_level,
    should_defer_to_human,
    should_seek_clarification,
    should_ignore_message,
    classify_response_action,
    check_nonsense_gate,
    has_workflow_signal,
    is_gibberish,
)

__all__ = [
    "classify_intent",
    "spans_multiple_steps",
    "get_qna_steps",
    "is_action_request",
    "QNA_TYPE_TO_STEP",
    "_detect_qna_types",
    "_looks_like_manager_request",
    "_RESUME_PHRASES",
    "CONFIDENCE_HIGH",
    "CONFIDENCE_MEDIUM",
    "CONFIDENCE_LOW",
    "CONFIDENCE_NONSENSE",
    "confidence_level",
    "should_defer_to_human",
    "should_seek_clarification",
    "should_ignore_message",
    "classify_response_action",
    "check_nonsense_gate",
    "has_workflow_signal",
    "is_gibberish",
]
