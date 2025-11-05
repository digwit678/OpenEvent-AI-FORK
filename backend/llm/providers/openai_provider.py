from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from backend.adapters.agent_adapter import get_agent_adapter

from .base import LLMProvider


class OpenAIProvider(LLMProvider):
    """Small wrapper that reuses the existing agent adapter for structured extraction."""

    def classify_extract(self, text: str) -> Dict[str, Any]:
        try:
            payload = json.loads(text)
            if not isinstance(payload, dict):
                payload = {"body": text}
        except json.JSONDecodeError:
            payload = {"body": text}
        adapter = get_agent_adapter()
        return adapter.analyze_message(payload)

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        raise NotImplementedError("chat is not implemented for the OpenAI provider.")

    def supports_json_schema(self) -> bool:
        return True
