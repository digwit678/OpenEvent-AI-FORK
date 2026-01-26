"""
Candidate Presentation Module (D-PRES extraction from step2_handler.py)

Extracted: 2026-01-23
Purpose: Message composition and draft building for date candidate presentation.

This module handles:
- Building message lines for date candidates
- Creating table rows and action buttons
- Assembling the final draft message
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from workflows.common.prompts import verbalize_draft_body
from workflows.common.timeutils import format_iso_date_to_ddmmyyyy

from .step2_utils import (
    _format_label_text,
    _preface_with_apology,
    _format_day_list,
)
from .date_parsing import (
    format_display_dates,
    human_join,
    safe_parse_iso_date,
)


def build_past_date_message(
    original_requested: date,
    future_suggestion: date,
) -> Tuple[str, str, str]:
    """
    Build message for past date with future suggestion.

    Returns:
        Tuple of (message_line, original_display, future_display)
    """
    original_display = (
        format_iso_date_to_ddmmyyyy(original_requested.isoformat())
        or original_requested.strftime("%d.%m.%Y")
    )
    future_display = (
        format_iso_date_to_ddmmyyyy(future_suggestion.isoformat())
        or future_suggestion.strftime("%d.%m.%Y")
    )
    message_line = f"Sorry, it looks like {original_display} has already passed. Would {future_display} work for you instead?"
    return message_line, original_display, future_display


def build_reason_message(reason: str) -> List[str]:
    """Build message lines for a given reason."""
    lines = []
    lines.append(_preface_with_apology(reason) or reason)
    lines.append("Here are some alternatives that might work:")
    return lines


def build_attempt_message(attempt: int) -> str:
    """Build message for retry attempts."""
    if attempt > 1:
        return "Let me show you some fresh options:"
    return "Here are some available dates:"


def build_unavailable_message(unavailable_requested: List[str]) -> List[str]:
    """Build message lines for unavailable requested dates."""
    lines = []
    unavailable_display = format_display_dates(unavailable_requested)
    joined = human_join(unavailable_display)
    verb = "is" if len(unavailable_requested) == 1 else "are"
    lines.append(f"Unfortunately {joined} {verb} not available.")
    lines.append("Would any of these work instead?")
    return lines


def build_weekday_shortfall_message() -> str:
    """Build message for weekday preference shortfall."""
    return "I couldn't find a free Thursday or Friday in that range. These are the closest available slots right now."


def build_date_list_lines(
    sample_dates: List[str],
    *,
    weekday_label: Optional[str],
    month_label: Optional[str],
    week_scope: Optional[dict],
    day_year: Optional[str],
    multi_month: bool,
) -> List[str]:
    """
    Build formatted date list lines for the message.

    Args:
        sample_dates: ISO date strings to display
        weekday_label: Optional weekday label (e.g., "Fridays")
        month_label: Optional month label (e.g., "March")
        week_scope: Optional week scope dict with 'label' key
        day_year: Year string for display
        multi_month: Whether dates span multiple months

    Returns:
        List of message lines
    """
    lines = []

    if multi_month:
        # Multi-month: show individual dates with month
        parsed_dates = [safe_parse_iso_date(iso) for iso in sample_dates]
        formatted_labels = [
            dt.strftime("%d %b %Y") for dt in parsed_dates if dt
        ]
        if formatted_labels:
            lines.append("")
            label_prefix = weekday_label or "Dates"
            lines.append(f"{label_prefix} coming up: {', '.join(formatted_labels)}")
            lines.append("")
    else:
        # Single month: show day numbers with month header
        from .step2_utils import _format_day_list
        day_line, _ = _format_day_list(sample_dates)

        if day_line and month_label and day_year:
            lines.append("")
            if week_scope:
                lines.append(
                    f"Dates available in {_format_label_text(week_scope['label'])} {day_year}: {day_line}"
                )
            else:
                label_prefix = weekday_label or "Dates"
                lines.append(
                    f"{label_prefix} available in {_format_label_text(month_label)} {day_year}: {day_line}"
                )
            lines.append("")

    return lines


def build_closing_prompt(future_display: Optional[str]) -> str:
    """Build the closing prompt asking for date selection."""
    if future_display:
        return f"Would **{future_display}** work for you? Or let me know another date you'd prefer."
    return "Just let me know which date works best and I'll check room availability for you."


def build_date_table_rows(
    formatted_dates: List[str],
    time_display: str,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """
    Build table rows for date display.

    Args:
        formatted_dates: ISO date strings
        time_display: Time display string (e.g., "Evening")
        limit: Max number of rows

    Returns:
        List of table row dicts
    """
    rows = []
    for iso_value in formatted_dates[:limit]:
        display_date = format_iso_date_to_ddmmyyyy(iso_value) or iso_value
        rows.append({
            "iso_date": iso_value,
            "display_date": display_date,
            "time_of_day": time_display,
        })
    return rows


def build_date_actions(
    formatted_dates: List[str],
    time_display: str,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """
    Build action buttons for date selection.

    Args:
        formatted_dates: ISO date strings
        time_display: Time display string
        limit: Max number of actions

    Returns:
        List of action dicts
    """
    actions = []
    for iso_value in formatted_dates[:limit]:
        display_date = format_iso_date_to_ddmmyyyy(iso_value) or iso_value
        actions.append({
            "type": "select_date",
            "label": f"{display_date} ({time_display})",
            "date": iso_value,
            "display_date": display_date,
        })
    return actions


def build_table_label(
    weekday_label: Optional[str],
    month_label: Optional[str],
    date_header_label: Optional[str],
    time_hint: Optional[str],
    time_display: str,
) -> str:
    """Build the label for the date table."""
    if weekday_label and month_label:
        label_base = f"{weekday_label} in {_format_label_text(month_label)}"
    elif month_label:
        label_base = f"Dates in {_format_label_text(month_label)}"
    else:
        label_base = date_header_label or "Candidate dates"

    if time_hint:
        label_base = f"{label_base} ({time_display})"

    return label_base


def assemble_candidate_draft(
    *,
    body_markdown: str,
    formatted_dates: List[str],
    table_rows: List[Dict[str, Any]],
    actions_payload: List[Dict[str, Any]],
    label_base: str,
    headers: List[str],
    escalate_to_hil: bool,
) -> Dict[str, Any]:
    """
    Assemble the final draft message for date candidates.

    Args:
        body_markdown: Verbalized message body
        formatted_dates: ISO date strings
        table_rows: Table row data
        actions_payload: Action button data
        label_base: Table label
        headers: Header lines
        escalate_to_hil: Whether to escalate to HIL

    Returns:
        Draft message dict
    """
    candidate_display = [
        format_iso_date_to_ddmmyyyy(iso) or iso
        for iso in formatted_dates[:5]
    ]

    draft = {
        "body": body_markdown,
        "body_markdown": body_markdown,
        "step": 2,
        "next_step": "Room Availability",
        "topic": "date_candidates",
        "candidate_dates": candidate_display,
        "table_blocks": [
            {
                "type": "dates",
                "label": label_base,
                "rows": table_rows,
            }
        ] if table_rows else [],
        "actions": actions_payload,
        "headers": headers,
    }

    thread_state_label = "Waiting on HIL" if escalate_to_hil else "Awaiting Client Response"
    draft["thread_state"] = thread_state_label
    draft["requires_approval"] = escalate_to_hil

    if escalate_to_hil:
        draft["hil_reason"] = "Client can't find suitable date, needs manual help"

    return draft


def verbalize_candidate_message(
    prompt: str,
    participants_count: Optional[int],
    formatted_dates: List[str],
) -> str:
    """
    Run the prompt through the universal verbalizer.

    Args:
        prompt: Raw message prompt
        participants_count: Number of participants
        formatted_dates: ISO date strings for context

    Returns:
        Verbalized markdown body
    """
    candidate_display = [
        format_iso_date_to_ddmmyyyy(iso) or iso
        for iso in formatted_dates[:5]
    ]

    return verbalize_draft_body(
        prompt,
        step=2,
        topic="date_candidates",
        participants_count=participants_count,
        candidate_dates=candidate_display,
    )
