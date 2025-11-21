from __future__ import annotations

import json
import os
from typing import Any, Dict

try:  # pragma: no cover - optional dependency
    from openai import OpenAI  # type: ignore
except Exception:  # pragma: no cover - dependency may be missing in tests
    OpenAI = None  # type: ignore

MODEL_NAME = os.getenv("OPEN_EVENT_QNA_VERBALIZER_MODEL", "gpt-4.1-mini")
_LLM_ENABLED = bool(os.getenv("OPENAI_API_KEY") and OpenAI is not None)

SYSTEM_PROMPT = (
    "You are OpenEvent's structured Q&A verbalizer. Craft concise markdown answers for clients "
    "using the provided structured context and query results. Keep tone helpful and factual."
)


def render_qna_answer(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert structured DB results into markdown answer blocks.

    When the gpt-4.1-mini runtime is unavailable, fall back to a deterministic formatter so tests
    remain stable.
    """

    if _LLM_ENABLED:
        try:
            return _call_llm(payload)
        except Exception:  # pragma: no cover - defensive guard
            pass
    return _fallback_answer(payload)


def _call_llm(payload: Dict[str, Any]) -> Dict[str, Any]:
    client = OpenAI()
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


def _fallback_answer(payload: Dict[str, Any]) -> Dict[str, Any]:
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
            descriptor = []
            if cap:
                descriptor.append(f"capacity up to {cap}")
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

    return {
        "model": "fallback",
        "body_markdown": "\n".join(lines).strip(),
        "used_fallback": True,
    }


__all__ = ["render_qna_answer"]
