"""Prompt formatting helpers shared across workflow trigger nodes."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

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
    if "check" in lookup:
        return "Checking"
    return "Awaiting Client"


def compose_footer(step: int, next_step: Union[int, str], thread_state: str) -> str:
    """Compose the standard footer string without mutating the body copy."""

    return f"Step: {_format_step_label(step)} · Next: {_format_next_step(next_step)} · State: {_normalize_thread_state(thread_state)}"


def append_footer(
    body: str,
    *,
    step: int,
    next_step: Union[int, str],
    thread_state: str,
    topic: Optional[str] = None,
    verbalize: bool = True,
    verbalize_context: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Append the standardized UX footer to a draft body.

    If verbalize=True and VERBALIZER_TONE=empathetic, the body will first be
    transformed through the universal verbalizer for warm, human-like output.

    Args:
        body: The message body text
        step: Current workflow step (1-7)
        next_step: Next step indicator (int or description)
        thread_state: Thread state label
        topic: Message topic for verbalization context
        verbalize: Whether to apply verbalization (default True)
        verbalize_context: Additional context for verbalization (dates, rooms, etc.)

    Returns:
        Body with footer appended (and optionally verbalized)
    """
    sanitized_body = body.rstrip()

    # Apply verbalization if enabled
    if verbalize and sanitized_body:
        sanitized_body = _verbalize_body(sanitized_body, step, topic, verbalize_context)

    footer = compose_footer(step, next_step, thread_state)
    return f"{sanitized_body}{FOOTER_SEPARATOR}{footer}"


def _verbalize_body(
    body: str,
    step: int,
    topic: Optional[str],
    context: Optional[Dict[str, Any]],
) -> str:
    """Apply universal verbalization to message body."""
    try:
        from ux.universal_verbalizer import verbalize_step_message

        # Extract context values with defaults
        ctx = context or {}

        return verbalize_step_message(
            body,
            step=step,
            topic=topic or "general",
            event_date=ctx.get("event_date"),
            participants_count=ctx.get("participants_count"),
            room_name=ctx.get("room_name"),
            room_status=ctx.get("room_status"),
            rooms=ctx.get("rooms"),
            total_amount=ctx.get("total_amount"),
            deposit_amount=ctx.get("deposit_amount"),
            products=ctx.get("products"),
            candidate_dates=ctx.get("candidate_dates"),
            client_name=ctx.get("client_name"),
            event_status=ctx.get("event_status"),
        )
    except Exception:
        # On any error, return original body
        return body


def verbalize_draft_body(
    body: str,
    *,
    step: int,
    topic: str,
    event_date: Optional[str] = None,
    participants_count: Optional[int] = None,
    room_name: Optional[str] = None,
    room_status: Optional[str] = None,
    rooms: Optional[List[Dict[str, Any]]] = None,
    total_amount: Optional[float] = None,
    deposit_amount: Optional[float] = None,
    products: Optional[List[Dict[str, Any]]] = None,
    candidate_dates: Optional[List[str]] = None,
    client_name: Optional[str] = None,
    event_status: Optional[str] = None,
) -> str:
    """
    Verbalize a draft message body for warm, human-like output.

    This is a convenience function for messages that don't go through append_footer.
    Use this when constructing body_markdown for draft messages.

    Args:
        body: The message body text
        step: Current workflow step (1-7)
        topic: Message topic (e.g., "offer_draft", "room_avail_result")
        ... (context fields for fact verification)

    Returns:
        Verbalized body text (or original if verbalization disabled/fails)
    """
    if not body or not body.strip():
        return body

    context = {
        "event_date": event_date,
        "participants_count": participants_count,
        "room_name": room_name,
        "room_status": room_status,
        "rooms": rooms,
        "total_amount": total_amount,
        "deposit_amount": deposit_amount,
        "products": products,
        "candidate_dates": candidate_dates,
        "client_name": client_name,
        "event_status": event_status,
    }
    return _verbalize_body(body, step, topic, context)


def format_sections_with_headers(sections: Sequence[Tuple[str, Sequence[str]]]) -> Tuple[str, List[str]]:
    """Compose body text from logical sections and return (body, headers)."""

    headers: List[str] = []
    lines: List[str] = []
    for header, content in sections:
        header_text = (header or "").strip()
        content_lines = [line for line in content if line is not None]
        if header_text:
            headers.append(header_text)
            lines.append(header_text)
        for line in content_lines:
            stripped = line.rstrip("\n")
            lines.append(stripped)
        if content_lines:
            lines.append("")
    body = "\n".join(line for line in lines if line is not None).strip()
    return body, headers
