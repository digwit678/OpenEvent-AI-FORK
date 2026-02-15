"""Tests for adapters/agent_adapter.py — Stub, OpenAI, Gemini adapters + factory."""
from __future__ import annotations

import json
import os
from collections import OrderedDict
from unittest.mock import MagicMock, patch

import pytest

from adapters.agent_adapter import (
    AgentAdapter,
    GeminiAgentAdapter,
    OpenAIAgentAdapter,
    StubAgentAdapter,
    get_agent_adapter,
    reset_agent_adapter,
)


# ============================================================================
# StubAgentAdapter (no mocks needed)
# ============================================================================

class TestStubAgentAdapter:
    """StubAgentAdapter is a deterministic heuristic adapter — no external calls."""

    def setup_method(self):
        self.adapter = StubAgentAdapter()

    # --- route_intent ---

    def test_route_intent_event_message(self):
        msg = {"subject": "Event booking request", "body": "I need a venue for 50 guests"}
        intent, confidence = self.adapter.route_intent(msg)
        assert intent == "event_request"
        assert confidence > 0.5

    def test_route_intent_non_event(self):
        msg = {"subject": "Hello", "body": "Just checking in"}
        intent, confidence = self.adapter.route_intent(msg)
        assert intent == "other"

    # --- extract_entities ---

    def test_extract_entities_date_eu(self):
        msg = {"body": "Meeting on 15.04.2026"}
        entities = self.adapter.extract_entities(msg)
        assert entities["date"] == "2026-04-15"

    def test_extract_entities_date_iso(self):
        msg = {"body": "Conference on 2026-06-20"}
        entities = self.adapter.extract_entities(msg)
        assert entities["date"] == "2026-06-20"

    def test_extract_entities_date_mdy(self):
        msg = {"body": "Party on March 15, 2026"}
        entities = self.adapter.extract_entities(msg)
        assert entities["date"] == "2026-03-15"

    def test_extract_entities_participants(self):
        msg = {"body": "dinner for 60 guests"}
        entities = self.adapter.extract_entities(msg)
        assert entities["participants"] == 60

    def test_extract_entities_room(self):
        msg = {"body": "We'd like Room A for the event"}
        entities = self.adapter.extract_entities(msg)
        assert entities["room"] is not None
        assert "a" in entities["room"].lower()

    def test_extract_entities_time(self):
        msg = {"body": "Event from 14:00 to 18:00"}
        entities = self.adapter.extract_entities(msg)
        assert entities["start_time"] == "14:00"
        assert entities["end_time"] == "18:00"

    # --- analyze_message ---

    def test_analyze_message_combined(self):
        msg = {"subject": "Event request", "body": "Book a room for 30 guests on 20.05.2026"}
        result = self.adapter.analyze_message(msg)
        assert "intent" in result
        assert "confidence" in result
        assert "fields" in result
        assert result["fields"]["participants"] == 30

    # --- complete ---

    def test_complete_returns_json(self):
        result = self.adapter.complete("What is the intent?")
        parsed = json.loads(result)
        assert "intent" in parsed
        assert "signals" in parsed


# ============================================================================
# OpenAIAgentAdapter (mock API client)
# ============================================================================

class TestOpenAIAgentAdapter:

    def _make_mock_response(self, content: dict):
        """Build a mock OpenAI chat completion response."""
        mock_choice = MagicMock()
        mock_choice.message.content = json.dumps(content)
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        return mock_response

    def test_route_intent_success(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = self._make_mock_response(
            {"intent": "event_request", "confidence": 0.95}
        )
        with patch("adapters.agent_adapter.get_openai_client", return_value=mock_client):
            adapter = OpenAIAgentAdapter()
        intent, conf = adapter.route_intent({"subject": "Booking", "body": "Need venue"})
        assert intent == "event_request"
        assert conf == 0.95

    def test_route_intent_fallback_on_error(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API down")
        with patch("adapters.agent_adapter.get_openai_client", return_value=mock_client):
            adapter = OpenAIAgentAdapter()
        # Should fallback to StubAgentAdapter, not raise
        intent, conf = adapter.route_intent({"subject": "Test", "body": "test"})
        assert isinstance(intent, str)

    def test_extract_entities_success(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = self._make_mock_response(
            {"date": "2026-05-20", "participants": 40, "room": "Room B"}
        )
        with patch("adapters.agent_adapter.get_openai_client", return_value=mock_client):
            adapter = OpenAIAgentAdapter()
        entities = adapter.extract_entities({"subject": "Booking", "body": "Event for 40"})
        assert entities["date"] == "2026-05-20"
        assert entities["participants"] == 40

    def test_extract_entities_fallback_on_error(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("fail")
        with patch("adapters.agent_adapter.get_openai_client", return_value=mock_client):
            adapter = OpenAIAgentAdapter()
        entities = adapter.extract_entities({"subject": "", "body": "60 guests dinner"})
        # Fallback to stub — should still find participants
        assert entities.get("participants") == 60


# ============================================================================
# GeminiAgentAdapter (mock API client)
# ============================================================================

class TestGeminiAgentAdapter:

    def _make_mock_response(self, content: dict):
        mock_response = MagicMock()
        mock_response.text = json.dumps(content)
        return mock_response

    def test_route_intent_success(self):
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = self._make_mock_response(
            {"intent": "event_request", "confidence": 0.9}
        )
        with patch("adapters.agent_adapter.genai") as mock_genai:
            mock_genai.Client.return_value = mock_client
            with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
                adapter = GeminiAgentAdapter()
        intent, conf = adapter.route_intent({"subject": "Venue", "body": "Need room"})
        assert intent == "event_request"

    def test_route_intent_fallback_on_error(self):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("Gemini error")
        with patch("adapters.agent_adapter.genai") as mock_genai:
            mock_genai.Client.return_value = mock_client
            with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
                adapter = GeminiAgentAdapter()
        intent, conf = adapter.route_intent({"subject": "Test", "body": "test"})
        assert isinstance(intent, str)  # Fallback should work


# ============================================================================
# Factory: get_agent_adapter()
# ============================================================================

class TestGetAgentAdapter:

    def setup_method(self):
        reset_agent_adapter()

    def teardown_method(self):
        reset_agent_adapter()

    def test_stub_mode(self):
        with patch.dict(os.environ, {"AGENT_MODE": "stub"}):
            adapter = get_agent_adapter()
        assert isinstance(adapter, StubAgentAdapter)

    def test_openai_mode(self):
        mock_client = MagicMock()
        with patch.dict(os.environ, {"AGENT_MODE": "openai"}), \
             patch("adapters.agent_adapter.get_openai_client", return_value=mock_client):
            adapter = get_agent_adapter()
        assert isinstance(adapter, OpenAIAgentAdapter)

    def test_gemini_mode(self):
        mock_client = MagicMock()
        with patch("adapters.agent_adapter.genai") as mock_genai, \
             patch.dict(os.environ, {"AGENT_MODE": "gemini", "GOOGLE_API_KEY": "test"}):
            mock_genai.Client.return_value = mock_client
            adapter = get_agent_adapter()
        assert isinstance(adapter, GeminiAgentAdapter)

    def test_hybrid_mode_uses_gemini(self):
        mock_client = MagicMock()
        with patch("adapters.agent_adapter.genai") as mock_genai, \
             patch.dict(os.environ, {"AGENT_MODE": "hybrid", "GOOGLE_API_KEY": "test"}):
            mock_genai.Client.return_value = mock_client
            adapter = get_agent_adapter()
        assert isinstance(adapter, GeminiAgentAdapter)

    def test_invalid_mode_raises(self):
        with patch.dict(os.environ, {"AGENT_MODE": "invalid_xyz"}):
            with pytest.raises(RuntimeError, match="Unsupported AGENT_MODE"):
                get_agent_adapter()


# ============================================================================
# Gateway: classify_intent via adapter.py
# ============================================================================

class TestClassifyIntentGateway:

    def setup_method(self):
        reset_agent_adapter()
        # Clear the analysis cache
        from workflows.llm.adapter import _ANALYSIS_CACHE
        _ANALYSIS_CACHE.clear()

    def teardown_method(self):
        reset_agent_adapter()

    def test_classify_intent_stub(self):
        with patch.dict(os.environ, {"AGENT_MODE": "stub"}):
            from workflows.llm.adapter import classify_intent, reset_llm_adapter
            reset_llm_adapter()
            intent, confidence = classify_intent(
                {"subject": "Booking venue for 50 guests", "body": "We need an event room"}
            )
        assert intent is not None
        assert isinstance(confidence, float)

    def test_cache_hit(self):
        with patch.dict(os.environ, {"AGENT_MODE": "stub"}):
            import workflows.llm.adapter as adapter_mod
            from workflows.llm.adapter import classify_intent, reset_llm_adapter
            reset_llm_adapter()
            adapter_mod._ANALYSIS_CACHE.clear()
            msg = {"subject": "Booking", "body": "Need a room for 20 guests"}
            intent1, _ = classify_intent(msg)
            # Second call should hit cache
            intent2, _ = classify_intent(msg)
            assert intent1 == intent2
            # Cache should have exactly 1 entry (access via module to avoid stale ref)
            assert len(adapter_mod._ANALYSIS_CACHE) == 1

    def test_fallback_on_provider_failure(self):
        """When provider fails, should fall back to StubAdapter."""
        with patch.dict(os.environ, {"AGENT_MODE": "stub"}):
            from workflows.llm.adapter import classify_intent, reset_llm_adapter, _ANALYSIS_CACHE
            reset_llm_adapter()
            _ANALYSIS_CACHE.clear()
            with patch("workflows.llm.adapter.get_provider") as mock_provider:
                mock_provider.return_value.classify_extract.side_effect = NotImplementedError("no impl")
                intent, confidence = classify_intent(
                    {"subject": "Test", "body": "test message"}
                )
            # Should still get a valid result from fallback
            assert intent is not None
