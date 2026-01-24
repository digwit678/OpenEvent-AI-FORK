"""Requirements fallback module.

This module handles the logic for falling back to existing requirements
when current user_info is missing fields.

Extracted from step1_handler.py for maintainability.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from workflows.common.requirements import build_requirements, requirements_hash

logger = logging.getLogger(__name__)


@dataclass
class RequirementsResult:
    """Result of requirements processing."""
    requirements: Dict[str, Any]
    requirements_hash: Optional[str]
    is_products_only_change: bool


def _needs_fallback(value: Any) -> bool:
    """Check if a value needs fallback from snapshot."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict)):
        return len(value) == 0
    return False


def apply_requirements_fallback(
    user_info: Dict[str, Any],
    requirements_snapshot: Dict[str, Any],
) -> None:
    """Apply fallback values from existing requirements to user_info.

    Mutates user_info in place with values from requirements_snapshot
    for any fields that are missing or empty.

    Args:
        user_info: Current user information (will be mutated)
        requirements_snapshot: Existing requirements from event_entry
    """
    if _needs_fallback(user_info.get("participants")) and requirements_snapshot.get("number_of_participants") is not None:
        user_info["participants"] = requirements_snapshot.get("number_of_participants")

    snapshot_layout = requirements_snapshot.get("seating_layout")
    if snapshot_layout:
        if _needs_fallback(user_info.get("layout")):
            user_info["layout"] = snapshot_layout
        if _needs_fallback(user_info.get("type")):
            user_info["type"] = snapshot_layout

    duration_snapshot = requirements_snapshot.get("event_duration")
    if isinstance(duration_snapshot, dict):
        if _needs_fallback(user_info.get("start_time")) and duration_snapshot.get("start"):
            user_info["start_time"] = duration_snapshot.get("start")
        if _needs_fallback(user_info.get("end_time")) and duration_snapshot.get("end"):
            user_info["end_time"] = duration_snapshot.get("end")

    snapshot_notes = requirements_snapshot.get("special_requirements")
    if snapshot_notes and _needs_fallback(user_info.get("notes")):
        user_info["notes"] = snapshot_notes

    snapshot_room = requirements_snapshot.get("preferred_room")
    if snapshot_room and _needs_fallback(user_info.get("room")):
        user_info["room"] = snapshot_room


def check_products_only_change(
    original_products_add: Any,
    original_products_remove: Any,
    original_notes: Any,
    original_has_requirements: bool,
) -> bool:
    """Check if this is a products-only change (not a requirements change).

    When a message only adds/removes products without changing core requirements,
    we should preserve existing requirements to avoid invalidating the hash.

    Args:
        original_products_add: products_add from original user_info
        original_products_remove: products_remove from original user_info
        original_notes: notes from original user_info
        original_has_requirements: True if original user_info had requirements

    Returns:
        True if this is a products-only change
    """
    notes_looks_like_product = any(p in (original_notes or "").lower() for p in [
        "projector", "screen", "microphone", "flipchart", "beamer", "av",
        "catering", "coffee", "tea", "lunch", "dinner",
    ]) if isinstance(original_notes, str) else False

    has_products_signal = original_products_add or original_products_remove or notes_looks_like_product
    return has_products_signal and not original_has_requirements


def has_original_requirements(user_info: Dict[str, Any]) -> bool:
    """Check if user_info has any core requirements fields set.

    Args:
        user_info: User information dict

    Returns:
        True if any requirements fields are set
    """
    return any([
        user_info.get("participants"),
        user_info.get("layout") or user_info.get("type"),
        user_info.get("start_time") or user_info.get("end_time"),
        user_info.get("date") or user_info.get("event_date"),
        user_info.get("room") or user_info.get("preferred_room"),
    ])


def process_requirements(
    user_info: Dict[str, Any],
    event_entry: Dict[str, Any],
) -> RequirementsResult:
    """Process requirements with fallback and products-only detection.

    Args:
        user_info: Current user information (will be mutated with fallback)
        event_entry: Current event record

    Returns:
        RequirementsResult with processed requirements
    """
    requirements_snapshot = event_entry.get("requirements") or {}

    # Save original products fields before fallback
    original_products_add = user_info.get("products_add")
    original_products_remove = user_info.get("products_remove")
    original_notes = user_info.get("notes")
    original_has_reqs = has_original_requirements(user_info)

    # Apply fallback from snapshot
    apply_requirements_fallback(user_info, requirements_snapshot)

    # Check if products-only change
    is_products_only = check_products_only_change(
        original_products_add,
        original_products_remove,
        original_notes,
        original_has_reqs,
    )

    logger.debug(
        "[Step1] Products check: original_notes=%s, has_products_signal=%s, "
        "original_has_requirements=%s, is_products_only=%s",
        original_notes, bool(original_products_add or original_products_remove),
        original_has_reqs, is_products_only,
    )

    if is_products_only and requirements_snapshot:
        # Keep existing requirements, don't rebuild from user_info
        logger.debug("[Step1] Products-only change detected, preserving existing requirements")
        return RequirementsResult(
            requirements=requirements_snapshot,
            requirements_hash=event_entry.get("requirements_hash"),
            is_products_only_change=True,
        )
    else:
        requirements = build_requirements(user_info)
        new_hash = requirements_hash(requirements)
        return RequirementsResult(
            requirements=requirements,
            requirements_hash=new_hash,
            is_products_only_change=False,
        )
