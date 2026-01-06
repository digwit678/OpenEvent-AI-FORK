from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from backend.adapters.agent_adapter import get_agent_adapter

from .base import LLMProvider


class OpenAIProvider(LLMProvider):
    """
    Thin provider wrapper that reuses the configured AgentAdapter (stub/OpenAI)
    to run combined intent + entity extraction. Named after the default runtime
    configuration where AGENT_MODE=openai.
    """

    def __init__(self) -> None:
        self._agent = get_agent_adapter

    def classify_extract(self, text: str) -> Dict[str, Any]:
        payload = self._decode_payload(text)
        agent = self._agent()
        result = agent.analyze_message(payload)
        if isinstance(result, dict):
            return result
        return {
            "intent": "other",
            "confidence": 0.0,
            "fields": {},
        }

    def chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
    ) -> Dict[str, Any]:
        raise NotImplementedError("Chat API is not implemented for the default provider.")

    def supports_json_schema(self) -> bool:
        return True

    @staticmethod
    def _decode_payload(text: Optional[str]) -> Dict[str, Any]:
        if not text:
            return {"subject": "", "body": ""}
        try:
            payload = json.loads(text)
        except (TypeError, ValueError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload.setdefault("subject", "")
        payload.setdefault("body", "")
        return payload


__all__ = ["OpenAIProvider"]
