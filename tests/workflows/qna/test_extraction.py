from __future__ import annotations

from pathlib import Path

from backend.workflows.common.types import IncomingMessage, WorkflowState
from backend.workflows.qna.extraction import ensure_qna_extraction


def _make_state() -> WorkflowState:
    message = IncomingMessage(
        msg_id="msg-42",
        from_name="Client",
        from_email="client@example.com",
        subject="",
        body="",
        ts=None,
    )
    state = WorkflowState(
        message=message,
        db_path=Path("."),
        db={},
    )
    return state


def test_borderline_message_triggers_extraction(monkeypatch):
    called = {}

    def fake_run(payload):
        called["payload"] = payload
        return {
            "msg_type": "event",
            "qna_intent": "select_static",
            "qna_subtype": "catalog_by_capacity",
            "q_values": {"n_exact": 45},
        }

    monkeypatch.setattr("backend.workflows.qna.extraction._run_qna_extraction", fake_run)

    state = _make_state()
    message_text = "Could you maybe share which spaces tend to work for about 45 ppl"
    result = ensure_qna_extraction(state, message_text, scan=None)

    assert result["qna_subtype"] == "catalog_by_capacity"
    assert state.extras["qna_extraction_meta"]["trigger"] in {"borderline", "general"}
    assert "payload" in called
