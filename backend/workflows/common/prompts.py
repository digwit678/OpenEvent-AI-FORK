"""Prompt formatting helpers shared across workflow trigger nodes."""

from __future__ import annotations

from typing import Union

FOOTER_SEPARATOR = "\n\n---\n"

STEP_LABELS = {
    1: "1 Intake",
    2: "2 Date Confirmation",
    3: "3 Room Availability",
    4: "4 Offer",
    5: "5 Event Preparation",
    6: "6 Contract",
    7: "7 Event Confirmation",
}


def _format_step_label(step: Union[int, str]) -> str:
    if isinstance(step, int):
        return STEP_LABELS.get(step, f"{step}")
    text = str(step).strip()
    if not text:
        return "?"
    if text[0].isdigit():
        return text
    return text.capitalize()


def _format_next_step(next_step: Union[int, str]) -> str:
    if isinstance(next_step, int):
        return STEP_LABELS.get(next_step, f"Step {next_step}")
    next_value = str(next_step).strip()
    if next_value.startswith("Step"):
        return next_value
    if next_value:
        return STEP_LABELS.get(int(next_value), f"Step {next_value}") if next_value.isdigit() else next_value
    return "Step ?"


def _normalize_thread_state(state: str) -> str:
    lookup = (state or "").strip().lower()
    if not lookup:
        return "Awaiting Client"
    if "hil" in lookup or "internal" in lookup:
        return "Waiting on HIL"
    if "await" in lookup and "client" in lookup:
        return "Awaiting Client"
    return "Awaiting Client"


def compose_footer(step: int, next_step: Union[int, str], thread_state: str) -> str:
    """Compose the standard footer string without mutating the body copy."""

    return f"Step: {_format_step_label(step)} · Next: {_format_next_step(next_step)} · State: {_normalize_thread_state(thread_state)}"


def append_footer(body: str, *, step: int, next_step: Union[int, str], thread_state: str) -> str:
    """Append the standardized UX footer to a draft body."""

    sanitized_body = body.rstrip()
    footer = compose_footer(step, next_step, thread_state)
    return f"{sanitized_body}{FOOTER_SEPARATOR}{footer}"
