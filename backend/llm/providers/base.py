from __future__ import annotations

from typing import Any, Dict, List, Optional


class LLMProvider:
    """Minimal interface expected by workflow adapters when delegating to LLM providers."""

    def classify_extract(self, text: str) -> Dict[str, Any]:
        """Return {intent, confidence, fields{...}} for the provided text."""

        raise NotImplementedError

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Chat wrapper that may return tool_calls; intentionally optional for providers."""

        raise NotImplementedError

    def supports_json_schema(self) -> bool:
        """Flag whether the provider natively supports JSON schema outputs."""

        return False
