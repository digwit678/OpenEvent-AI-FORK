"""
Regression test: HIL approval uses body (client message) not body_markdown (manager display)

BUG: When approving a Step 7 HIL task, the frontend showed the offer summary (body_markdown)
instead of the site visit prompt (body).

Root Cause: The draft stored in pending_hil_requests has:
- body: client-facing message (e.g., site visit prompt)
- body_markdown: manager-only display (e.g., offer summary)

When these differ, the approval code must use body for the client message.

Prevention: This test ensures body is always used when body != body_markdown.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
import pytest

from domain import TaskStatus, TaskType
from workflows.runtime.hil_tasks import approve_task_and_send


@pytest.fixture
def db_with_step7_hil_task(tmp_path: Path) -> tuple[Path, str, str]:
    """Create a database with a Step 7 HIL task where body != body_markdown."""
    task_id = "task-body-vs-markdown-test"
    event_id = "evt-test-body-markdown"

    # Client message vs manager display - they're DIFFERENT
    client_message = "We're excited to move forward with your event! Would you like to arrange a site visit?"
    manager_display = "Offer Summary:\n- Room A: CHF 500\n- Total: CHF 500\n\nDeposit paid: Yes"

    db = {
        "events": [
            {
                "event_id": event_id,
                "current_step": 7,
                "thread_state": "Waiting on HIL",
                "event_data": {"Email": "test@example.com"},
                "pending_hil_requests": [
                    {
                        "task_id": task_id,
                        "step": 7,
                        "type": "confirmation_message",
                        "thread_id": "thread-test",
                        "draft": {
                            "body": client_message,  # What client should see
                            "body_markdown": manager_display,  # What manager sees in HIL panel
                            "headers": [],
                        },
                    }
                ],
            }
        ],
        "tasks": [
            {
                "task_id": task_id,
                "type": TaskType.CONFIRMATION_MESSAGE.value,
                "event_id": event_id,
                "client_id": "test@example.com",
                "status": TaskStatus.PENDING.value,
                "payload": {
                    "step_id": 7,
                    "draft_msg": client_message,
                    "thread_id": "thread-test",
                },
            }
        ],
    }

    db_path = tmp_path / "events_database.json"
    db_path.write_text(json.dumps(db, indent=2))

    return db_path, task_id, client_message


def test_hil_approval_uses_body_not_body_markdown(db_with_step7_hil_task: tuple[Path, str, str]):
    """
    When body and body_markdown differ, HIL approval MUST use body (client message).

    Regression test for: After manager HIL approval, frontend showed offer summary
    instead of site visit prompt.
    """
    db_path, task_id, expected_client_message = db_with_step7_hil_task

    # Approve the task
    result = approve_task_and_send(task_id, db_path=db_path)

    # The assistant_draft_text should be the CLIENT message (body), not manager display
    actual_text = result.get("res", {}).get("assistant_draft_text", "")

    assert "site visit" in actual_text.lower(), (
        f"Expected site visit prompt in response, got: {actual_text[:200]}"
    )
    assert "Offer Summary" not in actual_text, (
        f"Response should NOT contain manager-only offer summary: {actual_text[:200]}"
    )

    # Also verify draft.body and draft.body_markdown are synced
    draft = result.get("draft", {})
    assert draft.get("body") == draft.get("body_markdown"), (
        "draft.body and draft.body_markdown should be synced to prevent frontend issues"
    )
    assert "site visit" in draft.get("body", "").lower(), (
        f"draft.body should be client message: {draft.get('body', '')[:100]}"
    )


def test_hil_approval_syncs_body_and_body_markdown(db_with_step7_hil_task: tuple[Path, str, str]):
    """
    After approval, both body and body_markdown should be set to the client message.

    This prevents the frontend from showing wrong content (it prioritizes body_markdown).
    """
    db_path, task_id, expected_client_message = db_with_step7_hil_task

    result = approve_task_and_send(task_id, db_path=db_path)

    draft = result.get("draft", {})
    body = draft.get("body", "")
    body_md = draft.get("body_markdown", "")

    # They must be identical after approval
    assert body == body_md, f"body and body_markdown must be synced. body={body[:100]}, md={body_md[:100]}"

    # And both should be the client message
    assert expected_client_message.split("!")[0] in body, (
        f"Expected client message fragment in body: {body[:100]}"
    )


def test_hil_approval_logs_warning_when_body_differs(db_with_step7_hil_task: tuple[Path, str, str], caplog):
    """
    When body != body_markdown, the system should log a warning for debugging.
    """
    import logging

    db_path, task_id, _ = db_with_step7_hil_task

    with caplog.at_level(logging.WARNING):
        approve_task_and_send(task_id, db_path=db_path)

    # Should have logged a warning about the difference
    warning_found = any(
        "[HIL_APPROVAL] body differs from body_markdown" in record.message
        for record in caplog.records
    )
    assert warning_found, (
        f"Expected warning about body/body_markdown difference. Logs: {[r.message for r in caplog.records]}"
    )
