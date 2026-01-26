"""
Step 3 Room Presentation and Formatting Functions.

Extracted from step3_handler.py as part of R7 refactoring (Jan 2026).

This module contains:
- compose_preselection_header: Compose lead sentence for draft
- verbalizer_rooms_payload: Build verbalizer payload
- format_requirements_line: Format requirements line
- format_room_sections: Format room sections for display
- format_range_descriptor: Format date range descriptor
- format_dates_list: Format dates list

Usage:
    from .room_presentation import (
        compose_preselection_header,
        verbalizer_rooms_payload,
        format_room_sections,
    )
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from workflows.common.sorting import RankedRoom
from workflows.common.timeutils import format_iso_date_to_ddmmyyyy
from workflows.steps.step3_room_availability.db_pers import load_rooms_config

from .constants import ROOM_OUTCOME_AVAILABLE, ROOM_OUTCOME_OPTION
from .selection import _format_display_date
from .room_ranking import derive_hint
from .conflict_resolution import _format_short_date


# -----------------------------------------------------------------------------
# Header Composition
# -----------------------------------------------------------------------------


def compose_preselection_header(
    status: str,
    room_name: Optional[str],
    chosen_date: str,
    participants: Optional[int],
    skip_capacity_prompt: bool,
) -> str:
    """Compose the lead sentence for the Step-3 draft before room selection."""

    date_label = _format_display_date(chosen_date)
    if status == ROOM_OUTCOME_AVAILABLE and room_name:
        if participants and not skip_capacity_prompt:
            return f"Good news — {room_name} is available on {date_label} and fits {participants} guests."
        return f"Good news — {room_name} is available on {date_label}."
    if status == ROOM_OUTCOME_OPTION and room_name:
        if participants and not skip_capacity_prompt:
            return f"Heads up — {room_name} is currently on option for {date_label}. It fits {participants} guests."
        return f"Heads up — {room_name} is currently on option for {date_label}."
    if participants and not skip_capacity_prompt:
        return f"I checked availability for {date_label} and captured the latest room status for {participants} guests."
    return f"I checked availability for {date_label} and captured the latest room status."


# -----------------------------------------------------------------------------
# Verbalizer Payload
# -----------------------------------------------------------------------------


def verbalizer_rooms_payload(
    ranked: List[RankedRoom],
    profiles: Dict[str, Dict[str, Any]],
    available_dates_map: Dict[str, List[str]],
    *,
    needs_products: Sequence[str],
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """Build payload for verbalizer with room details."""
    rooms_catalog = load_rooms_config() or []
    capacity_map = {}
    for item in rooms_catalog:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        capacity = (
            item.get("capacity_max")
            or item.get("capacity")
            or item.get("max_capacity")
            or item.get("capacity_maximum")
        )
        try:
            capacity_map[name] = int(capacity)
        except (TypeError, ValueError):
            capacity_map[name] = capacity
    payload: List[Dict[str, Any]] = []
    for entry in ranked[:limit]:
        profile = profiles.get(entry.room, {})
        badges_map = profile.get("requirements_badges") or {}
        coffee_badge = profile.get("coffee_badge", "—")
        capacity_badge = profile.get("capacity_badge", "—")
        normalized_products = {str(token).strip().lower() for token in needs_products}
        if "coffee" not in normalized_products and "tea" not in normalized_products and "drinks" not in normalized_products:
            coffee_badge = None
        alt_dates = [
            format_iso_date_to_ddmmyyyy(value) or value
            for value in available_dates_map.get(entry.room, [])
        ]
        hint_label = derive_hint(entry, None, bool(entry.matched or entry.missing))
        payload.append(
            {
                "id": entry.room,
                "name": entry.room,
                "capacity": capacity_map.get(entry.room),
                "badges": {
                    "coffee": coffee_badge,
                    "capacity": capacity_badge,
                    "u-shape": badges_map.get("u-shape") if "u-shape" in normalized_products else badges_map.get("u-shape"),
                    "projector": badges_map.get("projector") if "projector" in normalized_products else badges_map.get("projector"),
                },
                "requirements": {
                    "matched": list(entry.matched),
                    "closest": list(entry.closest),  # Partial matches with context
                    "missing": list(entry.missing),
                },
                "hint": hint_label,
                "alternatives": alt_dates,
            }
        )
    return payload


# -----------------------------------------------------------------------------
# Requirements Formatting
# -----------------------------------------------------------------------------


def format_requirements_line(requirements: Optional[Dict[str, Any]]) -> Optional[str]:
    """Format requirements as a display line with checkmarks."""
    if not isinstance(requirements, dict):
        return None
    matched = [str(item).strip() for item in requirements.get("matched", []) if str(item).strip()]
    missing = [str(item).strip() for item in requirements.get("missing", []) if str(item).strip()]
    tokens: List[str] = []
    tokens.extend(f"✔ {label}" for label in matched)
    tokens.extend(f"○ {label}" for label in missing)
    if not tokens:
        return None
    max_tokens = 4
    display = "; ".join(tokens[:max_tokens])
    overflow = len(tokens) - max_tokens
    if overflow > 0:
        display += f" (+{overflow} more)"
    return f"- Requirements: {display}"


# -----------------------------------------------------------------------------
# Room Sections Formatting
# -----------------------------------------------------------------------------


def format_room_sections(
    actions: List[Dict[str, Any]],
    mode: str,
    vague_month: Optional[Any],
    vague_weekday: Optional[Any],
) -> List[str]:
    """Format room sections for display with dates and requirements."""
    lines: List[str] = []
    if not actions:
        return lines

    descriptor = format_range_descriptor(vague_month, vague_weekday)
    max_display = 5 if mode == "range" else 3

    for action in actions:
        room = action.get("room")
        status = action.get("status") or "Available"
        hint = action.get("hint")
        iso_dates = action.get("available_dates") or []
        if not room:
            continue
        lines.append(f"### {room} — {status}")
        if hint:
            lines.append(f"- _{hint}_")
        requirements_line = format_requirements_line(action.get("requirements"))
        if requirements_line:
            lines.append(requirements_line)
        if iso_dates:
            display_text, remainder = format_dates_list(iso_dates, max_display)
            if mode == "range":
                prefix = "Available dates"
                if descriptor:
                    prefix += f" {descriptor}"
            else:
                prefix = "Alternative dates (closest)"
            line = f"- **{prefix}:** {display_text}"
            if remainder:
                line += f" (+{remainder} more)"
            lines.append(line)
        lines.append("")

    return lines


def format_range_descriptor(month_hint: Optional[Any], weekday_hint: Optional[Any]) -> str:
    """Format a descriptor for date range (e.g., 'in May (Friday)')."""
    parts: List[str] = []
    if month_hint:
        parts.append(str(month_hint).strip().capitalize())
    if weekday_hint:
        parts.append(str(weekday_hint).strip().capitalize())
    if not parts:
        return ""
    if len(parts) == 2:
        return f"in {parts[0]} ({parts[1]})"
    return f"in {parts[0]}"


def format_dates_list(dates: List[str], max_count: int) -> Tuple[str, int]:
    """Format a list of ISO dates for display."""
    shown = dates[:max_count]
    display = ", ".join(_format_short_date(iso) for iso in shown)
    remainder = max(0, len(dates) - max_count)
    return display, remainder


# -----------------------------------------------------------------------------
# Backward-compatible aliases (prefixed with underscore)
# -----------------------------------------------------------------------------

_compose_preselection_header = compose_preselection_header
_verbalizer_rooms_payload = verbalizer_rooms_payload
_format_requirements_line = format_requirements_line
_format_room_sections = format_room_sections
_format_range_descriptor = format_range_descriptor
_format_dates_list = format_dates_list


# -----------------------------------------------------------------------------
# Exports
# -----------------------------------------------------------------------------

__all__ = [
    # Public names
    "compose_preselection_header",
    "verbalizer_rooms_payload",
    "format_requirements_line",
    "format_room_sections",
    "format_range_descriptor",
    "format_dates_list",
    # Backward-compatible underscore aliases
    "_compose_preselection_header",
    "_verbalizer_rooms_payload",
    "_format_requirements_line",
    "_format_room_sections",
    "_format_range_descriptor",
    "_format_dates_list",
]
