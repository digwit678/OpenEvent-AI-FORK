"""Tests for unified detection signal merging.

These tests ensure LLM signals stay primary and pre-filter signals only
fill in safe gaps without overriding action requests.
"""
from __future__ import annotations

import pytest

from detection.pre_filter import PreFilterResult
from detection.unified import _merge_signal_flags

pytestmark = pytest.mark.v4


def test_DET_UNI_001_confirmation_not_qna_override() -> None:
    signals = {
        "is_confirmation": True,
        "is_acceptance": False,
        "is_rejection": False,
        "is_change_request": False,
        "is_manager_request": False,
        "is_question": False,
    }
    pre_filter = PreFilterResult(has_question_signal=True)

    merged = _merge_signal_flags(signals, pre_filter, intent="general_qna")

    assert merged["is_question"] is False
    assert merged["is_change_request"] is False


def test_DET_UNI_002_change_request_fallback() -> None:
    signals = {
        "is_confirmation": False,
        "is_acceptance": False,
        "is_rejection": False,
        "is_change_request": False,
        "is_manager_request": False,
        "is_question": True,
    }
    pre_filter = PreFilterResult(has_change_signal=True, has_question_signal=True)

    merged = _merge_signal_flags(signals, pre_filter, intent="event_request")

    assert merged["is_change_request"] is True
    assert merged["is_question"] is True
