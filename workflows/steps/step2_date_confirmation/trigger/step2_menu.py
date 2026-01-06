"""
D16b Refactoring: Menu handling for Step 2.

Extracted from step2_handler.py to reduce file size.
Contains menu request detection and response formatting.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from workflows.common.menu_options import (
    build_menu_title,
    extract_menu_request,
    format_menu_line,
    format_menu_line_short,
    MENU_CONTENT_CHAR_THRESHOLD,
    normalize_menu_for_display,
    select_menu_options,
)
from utils.pseudolinks import generate_qna_link
from utils.page_snapshots import create_snapshot
from workflows.common.types import WorkflowState

from .step2_utils import _format_label_text


def append_menu_options_if_requested(
    state: WorkflowState,
    message_lines: List[str],
    month_hint: Optional[str],
) -> None:
    """Attach a menu suggestion block when the client asks about menus.

    If the full content exceeds the display threshold, uses abbreviated format
    and adds a link to the full catering info page.

    Args:
        state: Current workflow state
        message_lines: List to append menu content to (modified in place)
        month_hint: Optional month context for menu filtering
    """
    request = extract_menu_request(
        (state.message.body or "") + "\n" + (state.message.subject or "")
    )
    if not request or not request.get("menu_requested"):
        return

    options = select_menu_options(request, month_hint=month_hint or request.get("month"))
    if not options:
        return

    title = build_menu_title(request)
    if month_hint:
        title = f"{title} ({_format_label_text(str(month_hint))})"

    # First render full content to check length
    full_lines = [title]
    for option in options:
        rendered = format_menu_line(option, month_hint=month_hint)
        if rendered:
            full_lines.append(rendered if rendered.lstrip().startswith("-") else f"- {rendered}")

    combined_len = len("\n".join(full_lines))

    # Build link params from workflow state (non-Q&A path)
    query_params: Dict[str, str] = {}
    event_entry = state.event_entry or {}
    user_info = state.user_info or {}
    requirements = event_entry.get("requirements") or {}

    # Date/month from workflow state
    chosen_date = event_entry.get("chosen_date")
    if chosen_date:
        query_params["date"] = str(chosen_date)
    elif month_hint:
        query_params["month"] = str(month_hint).lower()
    elif request.get("month"):
        query_params["month"] = str(request["month"]).lower()

    # Capacity from requirements or user_info
    capacity = (
        requirements.get("number_of_participants")
        or requirements.get("participants")
        or user_info.get("participants")
    )
    if capacity:
        try:
            query_params["capacity"] = str(int(capacity))
        except (TypeError, ValueError):
            pass

    # Menu request attributes
    if request.get("vegetarian"):
        query_params["vegetarian"] = "true"
    if request.get("wine_pairing"):
        query_params["wine_pairing"] = "true"
    if request.get("three_course"):
        query_params["courses"] = "3"

    # Create snapshot with full menu data for persistent link
    snapshot_data = {
        "menus": [normalize_menu_for_display(opt) for opt in options],
        "title": title,
        "request": request,
        "month_hint": month_hint,
        "full_lines": full_lines,
    }
    snapshot_id = create_snapshot(
        snapshot_type="catering",
        data=snapshot_data,
        event_id=getattr(state, "event_id", None),
        params=query_params,
    )
    shortcut_link = generate_qna_link(
        "Catering",
        query_params=query_params if query_params else None,
        snapshot_id=snapshot_id,
    )

    if combined_len > MENU_CONTENT_CHAR_THRESHOLD:
        # Use abbreviated format with link
        message_lines.append("")
        message_lines.append(f"Full menu details: {shortcut_link}")
        message_lines.append("")
        message_lines.append(title)
        for option in options:
            rendered = format_menu_line_short(option)
            if rendered:
                message_lines.append(rendered)
        state.extras["menu_shortcut"] = {
            "link": shortcut_link,
            "threshold": MENU_CONTENT_CHAR_THRESHOLD,
        }
    else:
        # Full content fits, but still add link at the end for reference
        message_lines.append("")
        message_lines.extend(full_lines)
        message_lines.append("")
        message_lines.append(f"Full menu details: {shortcut_link}")


__all__ = [
    "append_menu_options_if_requested",
]
