from __future__ import annotations

from types import SimpleNamespace

from workflows.nlu import (
    detect_general_room_query,
    reset_general_qna_cache,
)


def _state() -> SimpleNamespace:
    return SimpleNamespace(user_info={}, locale="en")


def test_detect_general_query_without_llm():
    reset_general_qna_cache()
    message = "Which rooms are free on Saturday evenings in February for ~30 people?"
    state = _state()

    result = detect_general_room_query(message, state)

    assert result["is_general"] is True
    assert result["llm_called"] is False
    assert result["constraints"]["vague_month"] == "february"
    assert result["constraints"]["time_of_day"] == "evening"
    assert result["constraints"]["pax"] == 30

    cached = detect_general_room_query(message, state)
    assert cached["cached"] is True


def test_detect_non_general_message():
    reset_general_qna_cache()
    message = "Please send menu options and pricing."
    state = _state()

    result = detect_general_room_query(message, state)

    assert result["is_general"] is False
    assert result["constraints"]["vague_month"] is None
