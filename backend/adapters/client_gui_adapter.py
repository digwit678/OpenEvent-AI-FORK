"""Adapters for emitting updates to the client-facing GUI."""

from __future__ import annotations

import json
from typing import Any, Dict


def _resolve_body_source(message: Dict[str, Any]) -> tuple[str, str]:
    candidates = [
        ("body_markdown", message.get("body_markdown")),
        ("body_md", message.get("body_md")),
        ("body", message.get("body")),
        ("prompt", message.get("prompt")),
    ]
    for field, value in candidates:
        if isinstance(value, str) and value:
            return value, field
    return "", "none"


def _render_plain(message: Dict[str, Any], resolved: str | None = None) -> str:
    """Render the message body using the plain fallback renderer."""
    body = resolved
    if body is None:
        body, _ = _resolve_body_source(message)
    renderer = globals().get("markdown_to_html")
    return renderer(body) if callable(renderer) else body


def adapt_message(message: Dict[str, Any]) -> Dict[str, Any]:
    """Prefer markdown fields when preparing a message for client rendering."""

    resolved, field = _resolve_body_source(message)
    adapted = dict(message)
    body_md = message.get("body_markdown") or message.get("body_md") or message.get("body") or ""
    rendered = body_md or _render_plain(message, resolved)
    adapted["render_body"] = rendered
    print(f"[WF][DEBUG][Adapter] body_chosen={field}")
    return adapted


class ClientGUIAdapter:
    """OpenEvent Action (light-blue): sync availability cards into the client-facing GUI."""

    def upsert_card(
        self,
        event_id: str,
        card_type: str,
        payload: Dict[str, Any],
        idempotency_key: str,
    ) -> None:
        payload = adapt_message(payload)
        print(f"[GUI] upsert_card event={event_id} card={card_type} id={idempotency_key}")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
