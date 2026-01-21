from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from llm.client import get_openai_client, is_llm_available
from workflows.common.fallback_reason import (
    FallbackReason,
    append_fallback_diagnostic,
    llm_disabled_reason,
    llm_exception_reason,
    empty_results_reason,
)

MODEL_NAME = os.getenv("OPEN_EVENT_QNA_VERBALIZER_MODEL", "gpt-4.1-mini")

SYSTEM_PROMPT = """You are an event manager replying to a client's email question. Write like a real person would in a business email - warm but concise.

RESPONSE STYLE:
- Answer the specific question asked, nothing more
- Write 1-3 sentences for simple questions (yes/no, does X have Y)
- For simple feature questions like "Does Room A have a projector?", just confirm: "Yes, Room A has a projector and screen."
- NO section headers like "Availability overview" or "Room Features:"
- NO bullet lists unless listing 4+ items
- Use natural paragraph flow, like an email reply

FORMATTING:
- Bold **room names**, **dates**, and **prices** only
- Separate distinct topics with a blank line
- Keep it conversational - imagine you're replying to a colleague

WHAT TO AVOID:
- "delve", "seamless", "elevate", "kindly", "please note"
- "I hope this finds you well", "Great news!", "I'm happy to help"
- Listing all room features when they only asked about one
- Repeating information they already know
- Generic filler sentences

EXAMPLE (good):
Client: "Does Room A have a projector?"
Reply: "Yes, **Room A** has a built-in projector and screen."

EXAMPLE (bad - too verbose):
Client: "Does Room A have a projector?"
Reply: "Availability overview\n\nRoom A Features:\n- Projector ✓\n- Screen ✓\n- WiFi..."
"""


def render_qna_answer(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert structured DB results into markdown answer blocks.

    When the gpt-4.1-mini runtime is unavailable, fall back to a deterministic formatter so tests
    remain stable.
    """
    fallback_reason: Optional[FallbackReason] = None

    if is_llm_available():
        try:
            return _call_llm(payload)
        except Exception as exc:  # pragma: no cover - defensive guard
            fallback_reason = llm_exception_reason("qna_verbalizer", exc)
    else:
        fallback_reason = llm_disabled_reason("qna_verbalizer")

    return _fallback_answer(payload, fallback_reason)


def _call_llm(payload: Dict[str, Any]) -> Dict[str, Any]:
    client = get_openai_client()
    response = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=0,
        top_p=0,
        max_tokens=600,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    )
    content = response.choices[0].message.content if response.choices else ""
    return {
        "model": MODEL_NAME,
        "body_markdown": content.strip(),
        "used_fallback": False,
    }


def _fallback_answer(
    payload: Dict[str, Any],
    fallback_reason: Optional[FallbackReason] = None,
) -> Dict[str, Any]:
    intent = payload.get("qna_intent")
    subtype = payload.get("qna_subtype")
    effective = payload.get("effective") or {}
    db_results = payload.get("db_results") or {}

    lines = [f"*Intent*: {intent} · *Subtype*: {subtype}"]

    room_rows = db_results.get("rooms") or []
    if room_rows:
        lines.append("")
        lines.append("**Rooms**")
        for entry in room_rows:
            name = entry.get("room_name") or entry.get("room_id")
            cap = entry.get("capacity_max")
            status = entry.get("status")
            rate_formatted = entry.get("daily_rate_formatted")
            descriptor = []
            if cap:
                descriptor.append(f"capacity up to {cap}")
            if rate_formatted:
                descriptor.append(f"{rate_formatted}/day")
            if status:
                descriptor.append(status)
            lines.append(f"- {name}{' (' + ', '.join(descriptor) + ')' if descriptor else ''}")

    product_rows = db_results.get("products") or []
    if product_rows:
        lines.append("")
        lines.append("**Products**")
        for entry in product_rows:
            name = entry.get("product")
            availability = "available" if entry.get("available_today") else "not currently available"
            lines.append(f"- {name}: {availability}")

    date_rows = db_results.get("dates") or []
    if date_rows:
        lines.append("")
        lines.append("**Dates**")
        for entry in date_rows:
            date_label = entry.get("date")
            room_label = entry.get("room_name") or entry.get("room_id")
            status = entry.get("status")
            lines.append(f"- {date_label} — {room_label} ({status})")

    notes = db_results.get("notes") or []
    if notes:
        lines.append("")
        for note in notes:
            lines.append(f"- {note}")

    if not lines:
        lines.append("Let me know if you'd like me to pull more details.")

    body = "\n".join(lines).strip()

    # Check if this is an empty result fallback (no rooms, dates, or products)
    rooms_count = len(room_rows)
    dates_count = len(date_rows)
    products_count = len(product_rows)

    if fallback_reason is None and rooms_count == 0 and dates_count == 0 and products_count == 0:
        fallback_reason = empty_results_reason(
            "qna_verbalizer",
            rooms_count=rooms_count,
            dates_count=dates_count,
            products_count=products_count,
        )

    # Append diagnostic info if we have a fallback reason
    if fallback_reason:
        # Add context about what data was available
        fallback_reason.context["rooms_count"] = rooms_count
        fallback_reason.context["dates_count"] = dates_count
        fallback_reason.context["products_count"] = products_count
        fallback_reason.context["intent"] = intent
        fallback_reason.context["subtype"] = subtype
        body = append_fallback_diagnostic(body, fallback_reason)

    return {
        "model": "fallback",
        "body_markdown": body,
        "used_fallback": True,
        "fallback_reason": fallback_reason.to_dict() if fallback_reason else None,
    }


__all__ = ["render_qna_answer"]
