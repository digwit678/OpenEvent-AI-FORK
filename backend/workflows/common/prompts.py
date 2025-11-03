"""Prompt formatting helpers shared across workflow trigger nodes."""

from __future__ import annotations

from typing import Union

FOOTER_SEPARATOR = "\n\n---\n"


def _format_next_step(next_step: Union[int, str]) -> str:
    if isinstance(next_step, int):
        return f"Step {next_step}"
    next_value = str(next_step).strip()
    if next_value.startswith("Step"):
        return next_value
    if next_value:
        return f"Step {next_value}" if next_value.isdigit() else next_value
    return "Step ?"


def append_footer(body: str, *, step: int, next_step: Union[int, str], thread_state: str) -> str:
    """Append the standardized UX footer to a draft body."""

    sanitized_body = body.rstrip()
    footer = f"Step: {step} | Next: {_format_next_step(next_step)} | State: {thread_state}"
    return f"{sanitized_body}{FOOTER_SEPARATOR}{footer}"

