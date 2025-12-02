from __future__ import annotations

"""
Confidence thresholds and utilities for detection confidence gating.
"""

# Threshold constants
CONFIDENCE_HIGH = 0.85
CONFIDENCE_MEDIUM = 0.65
CONFIDENCE_LOW = 0.40
CONFIDENCE_DEFER = 0.25


def should_defer_to_human(confidence: float) -> bool:
    """Return True if confidence is too low to auto-proceed."""
    return confidence < CONFIDENCE_DEFER


def should_seek_clarification(confidence: float) -> bool:
    """Return True if we should ask a clarifying question."""
    return confidence < CONFIDENCE_LOW


def confidence_level(score: float) -> str:
    """Return human-readable confidence level."""
    if score >= CONFIDENCE_HIGH:
        return "high"
    if score >= CONFIDENCE_MEDIUM:
        return "medium"
    if score >= CONFIDENCE_LOW:
        return "low"
    return "very_low"
