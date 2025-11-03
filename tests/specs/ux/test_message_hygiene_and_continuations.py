from pathlib import Path

from backend.workflows.common.types import IncomingMessage, WorkflowState


def _state(tmp_path: Path, step: int, thread_state: str = "Awaiting Client") -> WorkflowState:
    msg = IncomingMessage(msg_id="msg-ux", from_name=None, from_email=None, subject=None, body=None, ts=None)
    state = WorkflowState(message=msg, db_path=tmp_path / "db.json", db={"events": []})
    state.current_step = step
    state.set_thread_state(thread_state)
    return state


def test_footer_and_actions_present(tmp_path):
    state = _state(tmp_path, step=2)
    state.add_draft_message(
        {
            "body_markdown": "Here are some dates we can offer.",
            "step": 2,
            "next_step": "Confirm date",
            "thread_state": "Awaiting Client",
            "actions": [{"type": "select_date", "label": "Pick 10.11.2025", "date": "10.11.2025"}],
        }
    )

    draft = state.draft_messages[-1]
    assert draft["footer"].startswith("Step: 2 Date Confirmation")
    assert draft["actions"], "A continuation action must be present"
    assert len(draft["body_markdown"].splitlines()) <= 12


def test_waiting_on_hil_uses_clear_footer(tmp_path):
    state = _state(tmp_path, step=3, thread_state="Waiting on HIL")
    state.add_draft_message(
        {
            "body_markdown": "Awaiting internal approval before sharing the room decision.",
            "step": 3,
            "next_step": "Confirm availability",
            "thread_state": "Waiting on HIL",
        }
    )
    draft = state.draft_messages[-1]
    assert draft["footer"].endswith("State: Waiting on HIL")
    assert draft["actions"] == []
