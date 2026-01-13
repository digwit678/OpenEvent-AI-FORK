"""
Utility functions for accessing unified detection results in workflow handlers.

This module provides helpers to retrieve UnifiedDetectionResult from state.extras,
where it's stored as a dict after pre-routing.

Usage:
    from workflows.common.detection_utils import get_unified_detection

    detection = get_unified_detection(state)
    if detection and detection.is_acceptance:
        # Handle acceptance
"""

from __future__ import annotations

from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from workflows.common.types import WorkflowState

from detection.unified import UnifiedDetectionResult


def get_unified_detection(state: "WorkflowState") -> Optional[UnifiedDetectionResult]:
    """Get the unified detection result from state extras if available.

    The detection result is stored as a dict in state.extras["unified_detection"]
    after pre-routing. This function rebuilds the dataclass from the dict.

    Args:
        state: The current workflow state

    Returns:
        UnifiedDetectionResult if available, None otherwise
    """
    if not state or not state.extras:
        return None

    detection_data = state.extras.get("unified_detection")
    return _rebuild_from_dict(detection_data)


def get_unified_detection_from_dict(
    detection_data: Optional[Dict[str, Any]]
) -> Optional[UnifiedDetectionResult]:
    """Rebuild UnifiedDetectionResult from a dict.

    Useful when unified detection is passed directly as a dict parameter
    rather than accessed via state.

    Args:
        detection_data: Dict from state.extras["unified_detection"]

    Returns:
        UnifiedDetectionResult if valid dict, None otherwise
    """
    return _rebuild_from_dict(detection_data)


def _rebuild_from_dict(
    detection_data: Optional[Any]
) -> Optional[UnifiedDetectionResult]:
    """Internal helper to rebuild UnifiedDetectionResult from dict or return as-is."""
    if not detection_data:
        return None

    # If it's already the dataclass, return it
    if isinstance(detection_data, UnifiedDetectionResult):
        return detection_data

    # Rebuild from dict
    if isinstance(detection_data, dict):
        signals = detection_data.get("signals", {})
        entities = detection_data.get("entities", {})

        return UnifiedDetectionResult(
            language=detection_data.get("language", "en"),
            intent=detection_data.get("intent", "general_qna"),
            intent_confidence=detection_data.get("intent_confidence", 0.5),
            is_confirmation=signals.get("confirmation", False),
            is_acceptance=signals.get("acceptance", False),
            is_rejection=signals.get("rejection", False),
            is_change_request=signals.get("change_request", False),
            is_manager_request=signals.get("manager_request", False),
            is_question=signals.get("question", False),
            has_urgency=signals.get("urgency", False),
            date=entities.get("date"),
            date_text=entities.get("date_text"),
            participants=entities.get("participants"),
            duration_hours=entities.get("duration_hours"),
            room_preference=entities.get("room_preference"),
            products=entities.get("products", []),
            billing_address=entities.get("billing_address"),
            site_visit_room=entities.get("site_visit_room"),
            site_visit_date=entities.get("site_visit_date"),
            qna_types=detection_data.get("qna_types", []),
            step_anchor=detection_data.get("step_anchor"),
        )

    return None


__all__ = [
    "get_unified_detection",
    "get_unified_detection_from_dict",
]
