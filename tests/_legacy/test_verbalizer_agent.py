from __future__ import annotations

import os
from typing import Any, Dict, List


import pytest

from backend.llm.verbalizer_agent import verbalize_gui_reply  # type: ignore


@pytest.fixture(autouse=True)
def reset_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VERBALIZER_TONE", raising=False)
    monkeypatch.delenv("OPENAI_TEST_MODE", raising=False)


def test_verbalizer_disabled_returns_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    fallback = "AVAILABLE DATES:\n- 2025-12-10 18:00–22:00\nNEXT STEP:\nPick a date."
    result = verbalize_gui_reply([], fallback, client_email=None)
    assert result == fallback


def test_verbalizer_preserves_sections(monkeypatch: pytest.MonkeyPatch) -> None:
    fallback = (
        "AVAILABLE DATES:\n"
        "- 2025-12-10 18:00–22:00\n"
        "- 2025-12-11 18:00–22:00\n"
        "\nNEXT STEP:\nConfirm which option works best."
    )
    monkeypatch.setenv("VERBALIZER_TONE", "empathetic")
    monkeypatch.setenv("OPENAI_TEST_MODE", "1")

    def fake_call(payload: Dict[str, Any]) -> str:
        return (
            "Hi there! Here are the options you asked for:\n"
            "AVAILABLE DATES:\n"
            "- 2025-12-10 18:00–22:00\n"
            "- 2025-12-11 18:00–22:00\n"
            "\nNEXT STEP:\nConfirm which option works best."
        )

    monkeypatch.setattr("backend.llm.verbalizer_agent._call_verbalizer", fake_call)
    result = verbalize_gui_reply([], fallback, client_email="client@example.com")
    assert "Hi there!" in result
    assert "AVAILABLE DATES:" in result
    assert "- 2025-12-10 18:00–22:00" in result
    assert "NEXT STEP:" in result


def test_verbalizer_preserves_late_flow_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    fallback = (
        "OFFER:\n"
        "Price overview for your event.\n"
        "PRICE:\n"
        "- Room A — CHF 750\n"
        "VALID UNTIL:\n"
        "- 15.11.2025\n"
        "DEPOSIT:\n"
        "- CHF 150\n"
        "DEADLINE:\n"
        "- 30.10.2025\n"
        "AVAILABLE SLOTS:\n"
        "- 2025-11-20 10:00\n"
        "FOLLOW-UP:\n"
        "We'll reach out next week.\n"
    )
    monkeypatch.setenv("VERBALIZER_TONE", "empathetic")
    monkeypatch.setenv("OPENAI_TEST_MODE", "1")

    def fake_call(payload: Dict[str, Any]) -> str:
        return (
            "Thanks for confirming! Here's the summary:\n"
            + fallback
        )

    monkeypatch.setattr("backend.llm.verbalizer_agent._call_verbalizer", fake_call)
    result = verbalize_gui_reply([], fallback, client_email="client@example.com")
    for header in [
        "OFFER:",
        "PRICE:",
        "VALID UNTIL:",
        "DEPOSIT:",
        "DEADLINE:",
        "AVAILABLE SLOTS:",
        "FOLLOW-UP:",
    ]:
        assert header in result
def test_tone_plain_returns_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    fallback = "AVAILABLE DATES:\n- 2025-12-10 18:00–22:00\nNEXT STEP:\nPick a date."
    monkeypatch.setenv("VERBALIZER_TONE", "plain")
    result = verbalize_gui_reply([], fallback, client_email=None)
    assert result == fallback


def test_tone_fallback_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    fallback = (
        "AVAILABLE DATES:\n"
        "- 2025-12-10 18:00–22:00\n"
        "NEXT STEP:\nPick a date."
    )
    monkeypatch.setenv("VERBALIZER_TONE", "empathetic")

    def boom(_payload: Dict[str, Any]) -> str:
        raise RuntimeError("LLM failure")

    monkeypatch.setattr("backend.llm.verbalizer_agent._call_verbalizer", boom)
    result = verbalize_gui_reply([], fallback, client_email=None)
    assert result == fallback