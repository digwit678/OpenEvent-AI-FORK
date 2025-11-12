from __future__ import annotations

from typing import Any, Dict, List, Optional


class LLMProvider:
    """Abstract interface for LLM providers used by the workflow adapter."""

    def classify_extract(self, text: str) -> Dict[str, Any]:
        """
        Combined intent classification + entity extraction entrypoint.

        Implementations receive a JSON-encoded payload (subject/body/msg_id) and
        should return `{"intent": str, "confidence": float, "fields": {...}}`.
        """

        raise NotImplementedError("classify_extract must be implemented by subclasses.")

    def chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Optional helper for multi-turn chat integrations (unused for now)."""

        raise NotImplementedError("chat is not implemented for this provider.")

    def supports_json_schema(self) -> bool:
        """Return whether the provider natively enforces JSON schema outputs."""

        return False


__all__ = ["LLMProvider"]
