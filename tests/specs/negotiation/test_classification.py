"""
Characterization tests for Step5 classification helpers (N2 refactoring).

These tests lock down the behavior of the extracted classification functions.
"""

import pytest

from backend.workflows.steps.step5_negotiation.trigger.classification import (
    collect_detected_intents,
    classify_message,
    iso_to_ddmmyyyy,
)


class TestCollectDetectedIntents:
    """Tests for collect_detected_intents()."""

    def test_detects_acceptance(self):
        """Acceptance patterns produce 'accept' intent."""
        intents = collect_detected_intents("Yes, I accept the offer")
        intent_names = [i[0] for i in intents]
        assert "accept" in intent_names

    def test_detects_decline(self):
        """Decline patterns produce 'decline' intent."""
        intents = collect_detected_intents("No thank you, we decline")
        intent_names = [i[0] for i in intents]
        assert "decline" in intent_names

    def test_detects_counter_with_chf(self):
        """CHF amounts produce 'counter' intent."""
        intents = collect_detected_intents("Can we do CHF 500 instead?")
        intent_names = [i[0] for i in intents]
        assert "counter" in intent_names

    def test_detects_question(self):
        """Question marks produce 'clarification' intent."""
        intents = collect_detected_intents("What is included in the price?")
        intent_names = [i[0] for i in intents]
        assert "clarification" in intent_names

    def test_multiple_intents_possible(self):
        """Multiple intents can be detected from same message."""
        # A counter-offer with question mark triggers both counter and clarification
        intents = collect_detected_intents("Can we do CHF 400?")
        intent_names = [i[0] for i in intents]
        assert "counter" in intent_names
        assert "clarification" in intent_names

    def test_empty_message_returns_empty(self):
        """Empty message returns no intents."""
        assert collect_detected_intents("") == []
        assert collect_detected_intents(None) == []


class TestClassifyMessage:
    """Tests for classify_message()."""

    def test_returns_best_intent(self):
        """Returns highest confidence intent."""
        intent, confidence = classify_message("Yes, I accept")
        assert intent == "accept"
        assert confidence > 0.7

    def test_default_clarification(self):
        """Defaults to clarification for ambiguous messages."""
        intent, confidence = classify_message("hmm")
        assert intent == "clarification"
        assert confidence == 0.3

    def test_question_gets_clarification(self):
        """Question marks trigger clarification with moderate confidence."""
        intent, confidence = classify_message("?")
        assert intent == "clarification"
        assert confidence == 0.6


class TestIsoToDdmmyyyy:
    """Tests for iso_to_ddmmyyyy()."""

    def test_converts_valid_iso_date(self):
        """Converts YYYY-MM-DD to DD.MM.YYYY."""
        assert iso_to_ddmmyyyy("2026-02-14") == "14.02.2026"
        assert iso_to_ddmmyyyy("2025-12-31") == "31.12.2025"

    def test_returns_none_for_empty(self):
        """Returns None for empty/None input."""
        assert iso_to_ddmmyyyy("") is None
        assert iso_to_ddmmyyyy(None) is None

    def test_returns_none_for_invalid_format(self):
        """Returns None for non-ISO formats."""
        assert iso_to_ddmmyyyy("14.02.2026") is None
        assert iso_to_ddmmyyyy("2026/02/14") is None
        assert iso_to_ddmmyyyy("Feb 14, 2026") is None

    def test_strips_whitespace(self):
        """Handles whitespace around the date."""
        assert iso_to_ddmmyyyy("  2026-02-14  ") == "14.02.2026"
