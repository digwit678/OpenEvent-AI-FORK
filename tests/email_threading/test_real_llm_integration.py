"""Real LLM integration test for email threading.

This test verifies that:
1. Layer 1 (deterministic) resolves replies WITHOUT any LLM calls
2. Layer 2 only calls LLM when Layer 1 cannot resolve

Run with: pytest tests/email_threading/test_real_llm_integration.py -v -s
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from workflows.io.email_threading import is_reply, link_reply_to_thread, ThreadResolver


class TestLayer1NoLLMCalls:
    """Verify Layer 1 makes ZERO LLM calls."""

    def test_reply_detection_no_llm_call(self):
        """Layer 1 should detect reply via headers without ANY LLM involvement."""
        # Track if any LLM-related function is called
        llm_called = {"count": 0}

        def track_llm_call(*args, **kwargs):
            llm_called["count"] += 1
            raise AssertionError("LLM should NOT be called for reply detection!")

        # Patch all LLM entry points
        with patch("adapters.agent_adapter.get_agent_adapter") as mock_adapter:
            mock_adapter.return_value.complete = track_llm_call
            mock_adapter.return_value.analyze_message = track_llm_call

            # Test with In-Reply-To header
            headers = {
                "In-Reply-To": "<parent-msg@example.com>",
                "body": "Thanks for the info!",
            }

            is_reply_msg, parent_id = is_reply(headers)

            assert is_reply_msg is True
            assert parent_id == "parent-msg@example.com"
            assert llm_called["count"] == 0, "LLM was called but should not be!"

    def test_references_chain_no_llm_call(self):
        """Layer 1 should detect reply via References without LLM."""
        llm_called = {"count": 0}

        def track_llm_call(*args, **kwargs):
            llm_called["count"] += 1
            raise AssertionError("LLM should NOT be called!")

        with patch("adapters.agent_adapter.get_agent_adapter") as mock_adapter:
            mock_adapter.return_value.complete = track_llm_call

            headers = {
                "References": "<msg1@ex.com> <msg2@ex.com> <msg3@ex.com>",
                "body": "Following up on our conversation.",
            }

            is_reply_msg, parent_id = is_reply(headers)

            assert is_reply_msg is True
            assert parent_id == "msg3@ex.com"
            assert llm_called["count"] == 0

    def test_oe_token_no_llm_call(self):
        """Layer 1 should detect OE token without LLM."""
        llm_called = {"count": 0}

        def track_llm_call(*args, **kwargs):
            llm_called["count"] += 1
            raise AssertionError("LLM should NOT be called!")

        with patch("adapters.agent_adapter.get_agent_adapter") as mock_adapter:
            mock_adapter.return_value.complete = track_llm_call

            headers = {
                "body": "Quick question.\n\n[OE-abc12345]",
            }

            is_reply_msg, parent_id = is_reply(headers)

            assert is_reply_msg is True
            assert parent_id == "oe-token:abc12345"
            assert llm_called["count"] == 0


class TestLayer2OnlyWhenNeeded:
    """Verify Layer 2 LLM is only called when Layer 1 fails."""

    def test_new_email_triggers_llm(self):
        """New email (no reply headers) should trigger LLM resolver."""
        llm_called = {"count": 0}

        def mock_complete(prompt, **kwargs):
            llm_called["count"] += 1
            import json
            return json.dumps({
                "decision": "new_event",
                "confidence": 1.0,
                "reason": "No matching event found"
            })

        mock_agent = MagicMock()
        mock_agent.complete = mock_complete

        with patch("adapters.agent_adapter.get_agent_adapter", return_value=mock_agent):
            db = {
                "events": [{
                    "event_id": "evt-001",
                    "status": "Lead",
                    "created_at": "2026-01-15T10:00:00Z",
                    "event_data": {"Email": "client@example.com"},
                }],
                "email_messages": [],
                "thread_mappings": [],
            }

            resolver = ThreadResolver()
            result = resolver.resolve(
                email_from="client@example.com",
                email_subject="New inquiry",
                email_body="I'd like to book a venue.",
                db=db,
            )

            assert llm_called["count"] == 1, "LLM should be called exactly once for new emails"

    def test_reply_email_skips_llm(self):
        """Reply email (with headers) should NOT trigger LLM in full flow."""
        # This tests the full integration in event_bootstrap
        from pathlib import Path
        from workflows.steps.step1_intake.trigger.event_bootstrap import (
            _has_email_headers,
            _resolve_email_thread,
        )
        from workflows.common.types import WorkflowState, IncomingMessage

        llm_called = {"count": 0}

        def track_llm(*args, **kwargs):
            llm_called["count"] += 1
            raise AssertionError("LLM should NOT be called for replies!")

        mock_agent = MagicMock()
        mock_agent.complete = track_llm

        with patch("adapters.agent_adapter.get_agent_adapter", return_value=mock_agent):
            # Setup: message payload with reply headers
            message_payload = {
                "msg_id": "reply-001",
                "from_email": "client@example.com",
                "subject": "Re: Your booking",
                "body": "Thanks!",
                "headers": {
                    "Message-ID": "<reply-001@client.com>",
                    "In-Reply-To": "<orig-001@venue.com>",
                },
            }

            # Setup: database with the parent message
            db = {
                "events": [{
                    "event_id": "evt-001",
                    "status": "Lead",
                    "event_data": {"Email": "client@example.com"},
                }],
                "email_messages": [{
                    "message_id": "orig-001@venue.com",
                    "from_address": "client@example.com",
                    "resolved_event_id": "evt-001",
                }],
                "thread_mappings": [],
            }

            # Create minimal state
            msg = IncomingMessage(
                msg_id="reply-001",
                from_email="client@example.com",
                from_name="Client",
                subject="Re: Your booking",
                body="Thanks!",
                ts="2026-01-20T10:00:00Z",
                extras={},
            )
            state = WorkflowState(message=msg, db_path=Path("/tmp/test.json"), db=db)
            state.client_id = "client@example.com"

            # Verify headers are detected
            assert _has_email_headers(message_payload) is True

            # Run thread resolution
            resolved_event, was_resolved = _resolve_email_thread(
                state, message_payload, "test-thread"
            )

            # Should resolve via Layer 1 (deterministic) without LLM
            assert was_resolved is True
            assert resolved_event is not None
            assert resolved_event["event_id"] == "evt-001"
            assert llm_called["count"] == 0, "LLM should NOT be called for reply emails!"


@pytest.mark.skipif(
    not __import__("os").getenv("RUN_REAL_LLM_TESTS"),
    reason="Set RUN_REAL_LLM_TESTS=1 to run with real LLM"
)
class TestRealLLMIntegration:
    """Tests that actually call the real LLM. Skipped by default."""

    def test_real_llm_semantic_matching(self):
        """Test Layer 2 with actual LLM call."""
        db = {
            "events": [{
                "event_id": "evt-workshop",
                "status": "Lead",
                "chosen_date": "15.03.2026",
                "created_at": "2026-01-15T10:00:00Z",
                "event_data": {
                    "Email": "sarah@corp.com",
                    "Type of Event": "Workshop",
                    "Number of Participants": "25",
                },
            }],
            "email_messages": [],
            "thread_mappings": [],
        }

        resolver = ThreadResolver()
        result = resolver.resolve(
            email_from="sarah@corp.com",
            email_subject="Question about March workshop",
            email_body="For our workshop on March 15th with 25 participants, do you have projectors?",
            db=db,
        )

        print(f"\nReal LLM Result: {result}")
        print(f"  Decision: {result.decision}")
        print(f"  Event ID: {result.event_id}")
        print(f"  Confidence: {result.confidence}")
        print(f"  Reason: {result.reason}")

        # The LLM should recognize this is about the existing workshop
        # (though we don't assert exact behavior since LLM responses vary)
