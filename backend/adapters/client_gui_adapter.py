"""Adapters for emitting updates to the client-facing GUI."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


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
    logger.debug("[WF][DEBUG][Adapter] body_chosen=%s", field)
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
        logger.debug("[GUI] upsert_card event=%s card=%s id=%s", event_id, card_type, idempotency_key)
        logger.debug("Payload: %s", json.dumps(payload, indent=2, ensure_ascii=False))
