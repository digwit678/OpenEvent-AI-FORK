from __future__ import annotations

import json

from backend.llm import provider_registry
from backend.llm.providers.base import LLMProvider
from backend.workflows.llm import adapter as llm_adapter


class DummyProvider(LLMProvider):
    def classify_extract(self, text: str):  # type: ignore[override]
        payload = json.loads(text)
        return {
            "intent": "event_request",
            "confidence": 0.8,
            "fields": {"participants": payload.get("body", "").count(" ") + 1},
        }

    def chat(self, messages, tools=None, tool_choice=None):  # pragma: no cover - not used
        raise NotImplementedError


def test_provider_fallback_without_match_catalog(monkeypatch):
    provider_registry.reset_provider_for_tests()
    monkeypatch.setattr(provider_registry, "get_provider", lambda: DummyProvider())

    class MinimalAdapter:
        def analyze_message(self, payload):  # pragma: no cover - should not be called
            return {"intent": "event_request", "confidence": 0.9, "fields": {}}

    monkeypatch.setattr(llm_adapter, "get_agent_adapter", lambda: MinimalAdapter())
    llm_adapter.reset_llm_adapter()

    info = llm_adapter.extract_user_information({"body": "Projector needed"})
    assert isinstance(info, dict)
    assert "participants" in info