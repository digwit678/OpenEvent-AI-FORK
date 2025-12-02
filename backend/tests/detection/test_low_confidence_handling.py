import pytest

from backend.workflows.common.confidence import should_seek_clarification
from backend.workflows.groups import negotiation_close


class DummyState:
    def __init__(self) -> None:
        self.client_id = "client-1"
        self.intent = None
        self.confidence = 0.0
        self.draft_messages = []
        self.thread_state = ""
        self.context_snapshot = {}
        self.extras = {}
        self.current_step = None
        self.user_info = {}

    def add_draft_message(self, draft):
        self.draft_messages.append(draft)

    def set_thread_state(self, value: str) -> None:
        self.thread_state = value


@pytest.fixture(autouse=True)
def stub_update_event_metadata(monkeypatch):
    monkeypatch.setattr(negotiation_close, "update_event_metadata", lambda *args, **kwargs: None)


def test_low_confidence_triggers_clarification():
    state = DummyState()
    event_entry = {}
    classification, confidence = negotiation_close._classify_message("maybe")

    assert should_seek_clarification(confidence)
    result = negotiation_close._ask_classification_clarification(
        state,
        event_entry,
        "maybe",
        [("clarification", confidence)],
        confidence=confidence,
    )

    assert result.halt is True
    assert state.thread_state == "Awaiting Client Response"
    assert state.draft_messages[-1]["requires_approval"] is False


def test_clarification_message_contains_options():
    state = DummyState()
    event_entry = {}
    result = negotiation_close._ask_classification_clarification(
        state,
        event_entry,
        "sounds good but maybe negotiate",
        [("accept", 0.8), ("counter", 0.7)],
        confidence=0.3,
    )

    body = state.draft_messages[-1]["body"]
    assert "confirm the booking" in body
    assert "discuss pricing" in body
    assert result.halt is True


def test_high_confidence_skips_clarification_threshold():
    classification, confidence = negotiation_close._classify_message("Yes please proceed")
    assert classification == "accept"
    assert confidence >= 0.7
    assert not should_seek_clarification(confidence)


def test_room_selection_classifies_separately():
    classification, confidence = negotiation_close._classify_message("Room A looks good")
    assert classification == "room_selection"
    assert confidence >= 0.8


def test_very_low_confidence_defers_to_human():
    state = DummyState()
    event_entry = {}
    result = negotiation_close._ask_classification_clarification(
        state,
        event_entry,
        "unclear",
        [("clarification", 0.1)],
        confidence=0.1,
    )
    assert state.draft_messages[-1]["requires_approval"] is True
    assert result.halt is True
