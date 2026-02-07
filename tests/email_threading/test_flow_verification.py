"""Flow verification test - demonstrates Layer 1 vs Layer 2 behavior.

This test clearly shows:
1. Reply emails (with headers) → Layer 1 resolves → NO LLM call
2. New emails (no headers) → Layer 2 resolves → LLM IS called

Run with: pytest tests/email_threading/test_flow_verification.py -v -s
"""
from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from workflows.io.email_threading import is_reply, link_reply_to_thread, ThreadResolver
from workflows.steps.step1_intake.trigger.event_bootstrap import (
    _has_email_headers,
    _resolve_email_thread,
)
from workflows.common.types import WorkflowState, IncomingMessage


class TestLayerFlows:
    """Verify the two-layer resolution flow."""

    @pytest.fixture
    def db_with_history(self):
        """Database with email history for linking."""
        return {
            "events": [{
                "event_id": "evt-march-workshop",
                "status": "Lead",
                "chosen_date": "15.03.2026",
                "created_at": "2026-01-15T10:00:00Z",
                "event_data": {
                    "Email": "sarah@corp.com",
                    "Type of Event": "Workshop",
                    "Number of Participants": "25",
                },
            }],
            "email_messages": [{
                "message_id": "orig-001@venue.com",
                "from_address": "sarah@corp.com",
                "resolved_event_id": "evt-march-workshop",
            }],
            "thread_mappings": [],
        }

    def test_flow_layer1_reply_no_llm(self, db_with_history, capsys):
        """FLOW 1: Reply email → Layer 1 → NO LLM call."""
        print("\n" + "="*60)
        print("FLOW 1: Reply Email (In-Reply-To header)")
        print("="*60)

        llm_call_count = [0]

        def track_llm_call(*args, **kwargs):
            llm_call_count[0] += 1
            print(f"  ❌ LLM CALLED (this should not happen for replies!)")
            import json
            return json.dumps({"decision": "new_event", "confidence": 1.0})

        mock_agent = MagicMock()
        mock_agent.complete = track_llm_call

        with patch("adapters.agent_adapter.get_agent_adapter", return_value=mock_agent):
            # Email with reply headers
            message_payload = {
                "msg_id": "reply-001",
                "from_email": "sarah@corp.com",
                "subject": "Re: Your workshop booking",
                "body": "Thanks, March 15th works great!",
                "headers": {
                    "Message-ID": "<reply-001@client.com>",
                    "In-Reply-To": "<orig-001@venue.com>",
                },
            }

            print(f"\nInput:")
            print(f"  Subject: {message_payload['subject']}")
            print(f"  In-Reply-To: {message_payload['headers']['In-Reply-To']}")

            # Step 1: Check if has email headers
            has_headers = _has_email_headers(message_payload)
            print(f"\nStep 1: Has email headers? {has_headers}")

            # Step 2: Layer 1 - Reply detection
            headers = {**message_payload.get("headers", {}), "body": message_payload.get("body", "")}
            is_reply_msg, parent_id = is_reply(headers)
            print(f"Step 2: Is reply? {is_reply_msg} (parent: {parent_id})")

            # Step 3: Link to thread
            event_id = link_reply_to_thread(
                parent_id,
                db_with_history["email_messages"],
                db_with_history["thread_mappings"],
            )
            print(f"Step 3: Linked to event: {event_id}")

            # Verify
            print(f"\nResult:")
            print(f"  ✅ Resolved via Layer 1 (deterministic)")
            print(f"  ✅ LLM calls: {llm_call_count[0]} (expected: 0)")
            print(f"  ✅ Event: {event_id}")

            assert is_reply_msg is True
            assert event_id == "evt-march-workshop"
            assert llm_call_count[0] == 0

    def test_flow_layer2_new_email_with_llm(self, db_with_history, capsys):
        """FLOW 2: New email (no headers) → Layer 2 → LLM IS called."""
        print("\n" + "="*60)
        print("FLOW 2: New Email (no reply headers)")
        print("="*60)

        llm_call_count = [0]
        llm_prompt_received = [None]

        def capture_llm_call(prompt, **kwargs):
            llm_call_count[0] += 1
            llm_prompt_received[0] = prompt[:200] + "..."
            print(f"  ✅ LLM CALLED (expected for new emails)")
            import json
            return json.dumps({
                "decision": "attach",
                "event_id": "evt-march-workshop",
                "confidence": 0.92,
                "reason": "Email mentions March 15 workshop with 25 participants"
            })

        mock_agent = MagicMock()
        mock_agent.complete = capture_llm_call

        with patch("adapters.agent_adapter.get_agent_adapter", return_value=mock_agent):
            # Email WITHOUT reply headers
            message_payload = {
                "msg_id": "new-001",
                "from_email": "sarah@corp.com",
                "subject": "Question about March workshop",
                "body": "For our March 15th workshop with 25 people, do you have projectors?",
                "headers": {
                    "Message-ID": "<new-001@client.com>",
                    # No In-Reply-To, no References
                },
            }

            print(f"\nInput:")
            print(f"  Subject: {message_payload['subject']}")
            print(f"  Body: {message_payload['body'][:50]}...")
            print(f"  In-Reply-To: (none)")

            # Step 1: Check if has email headers (yes, but no reply headers)
            has_headers = _has_email_headers(message_payload)
            print(f"\nStep 1: Has email headers? {has_headers}")

            # Step 2: Layer 1 - Reply detection (should fail)
            headers = {**message_payload.get("headers", {}), "body": message_payload.get("body", "")}
            is_reply_msg, parent_id = is_reply(headers)
            print(f"Step 2: Is reply? {is_reply_msg}")

            # Step 3: Layer 2 - LLM resolution (should trigger)
            resolver = ThreadResolver()
            result = resolver.resolve(
                email_from="sarah@corp.com",
                email_subject=message_payload["subject"],
                email_body=message_payload["body"],
                db=db_with_history,
            )
            print(f"Step 3: LLM resolved to: {result.decision} (event: {result.event_id})")

            # Verify
            print(f"\nResult:")
            print(f"  ✅ Layer 1 failed (no reply headers)")
            print(f"  ✅ Layer 2 triggered (LLM called)")
            print(f"  ✅ LLM calls: {llm_call_count[0]} (expected: 1)")
            print(f"  ✅ Decision: {result.decision}")
            print(f"  ✅ Event: {result.event_id}")
            print(f"  ✅ Confidence: {result.confidence}")

            assert is_reply_msg is False
            assert llm_call_count[0] == 1
            assert result.decision == "attach"
            assert result.event_id == "evt-march-workshop"

    def test_flow_comparison(self, db_with_history, capsys):
        """Side-by-side comparison of both flows."""
        print("\n" + "="*60)
        print("COMPARISON: Reply vs New Email")
        print("="*60)

        results = {"reply": {}, "new": {}}
        llm_counts = {"reply": 0, "new": 0}

        def make_tracker(key):
            def track(*args, **kwargs):
                llm_counts[key] += 1
                import json
                return json.dumps({"decision": "attach", "event_id": "evt-march-workshop", "confidence": 0.9})
            return track

        # Test reply email
        mock_agent = MagicMock()
        mock_agent.complete = make_tracker("reply")

        with patch("adapters.agent_adapter.get_agent_adapter", return_value=mock_agent):
            headers = {"In-Reply-To": "<orig-001@venue.com>", "body": "Thanks!"}
            is_reply_msg, parent_id = is_reply(headers)
            if is_reply_msg:
                event_id = link_reply_to_thread(parent_id, db_with_history["email_messages"], [])
                results["reply"] = {"method": "Layer 1", "event_id": event_id}

        # Test new email
        mock_agent = MagicMock()
        mock_agent.complete = make_tracker("new")

        with patch("adapters.agent_adapter.get_agent_adapter", return_value=mock_agent):
            headers = {"body": "Question about the workshop"}
            is_reply_msg, _ = is_reply(headers)
            if not is_reply_msg:
                resolver = ThreadResolver()
                result = resolver.resolve(
                    email_from="sarah@corp.com",
                    email_subject="Question",
                    email_body="Question about the March workshop",
                    db=db_with_history,
                )
                results["new"] = {"method": "Layer 2", "event_id": result.event_id}

        print("\n┌─────────────────┬──────────────┬──────────┬────────────────────┐")
        print("│ Email Type      │ Resolution   │ LLM Calls│ Result             │")
        print("├─────────────────┼──────────────┼──────────┼────────────────────┤")
        print(f"│ Reply (headers) │ {results['reply']['method']:<12} │ {llm_counts['reply']:<8} │ {results['reply']['event_id'] or 'N/A':<18} │")
        print(f"│ New (no headers)│ {results['new']['method']:<12} │ {llm_counts['new']:<8} │ {results['new']['event_id'] or 'N/A':<18} │")
        print("└─────────────────┴──────────────┴──────────┴────────────────────┘")

        assert llm_counts["reply"] == 0, "Reply should NOT trigger LLM"
        assert llm_counts["new"] == 1, "New email should trigger LLM"
