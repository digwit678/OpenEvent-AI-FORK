"""Tests for Layer 1: Reply detection (NO LLM required).

These tests verify that reply detection works correctly using
email headers without requiring any LLM calls.
"""
from __future__ import annotations

import pytest
from workflows.io.email_threading import (
    is_reply,
    link_reply_to_thread,
    store_email_message,
    create_thread_mapping,
)


class TestIsReply:
    """Tests for is_reply() function."""

    def test_detects_reply_via_in_reply_to(self, email_with_reply_headers):
        """Should detect reply when In-Reply-To header is present."""
        headers = email_with_reply_headers["headers"]
        headers["body"] = email_with_reply_headers.get("body", "")

        is_reply_msg, parent_id = is_reply(headers)

        assert is_reply_msg is True
        assert parent_id == "orig-msg-001@venue.com"

    def test_detects_reply_via_references(self, email_with_references_chain):
        """Should detect reply when References header chain is present."""
        headers = email_with_references_chain["headers"]
        headers["body"] = email_with_references_chain.get("body", "")

        is_reply_msg, parent_id = is_reply(headers)

        assert is_reply_msg is True
        # Should return the last reference (immediate parent)
        assert parent_id == "chain-msg-002@venue.com"

    def test_detects_reply_via_oe_token(self, email_with_oe_token):
        """Should detect reply when OE token is present in body."""
        headers = email_with_oe_token["headers"]
        headers["body"] = email_with_oe_token["body"]

        is_reply_msg, parent_id = is_reply(headers)

        assert is_reply_msg is True
        assert parent_id == "oe-token:evt001ab"

    def test_not_reply_when_no_headers(self, new_email_same_event_details):
        """Should not detect reply when no reply headers are present."""
        headers = new_email_same_event_details["headers"]
        headers["body"] = new_email_same_event_details.get("body", "")

        is_reply_msg, parent_id = is_reply(headers)

        assert is_reply_msg is False
        assert parent_id is None

    def test_prefers_in_reply_to_over_references(self):
        """Should prefer In-Reply-To when both headers are present."""
        headers = {
            "In-Reply-To": "<direct-parent@example.com>",
            "References": "<old-msg@example.com> <different-parent@example.com>",
            "body": "",
        }

        is_reply_msg, parent_id = is_reply(headers)

        assert is_reply_msg is True
        assert parent_id == "direct-parent@example.com"

    def test_handles_angle_brackets_in_message_id(self):
        """Should clean angle brackets from Message-ID."""
        headers = {
            "In-Reply-To": "<msg-with-brackets@example.com>",
            "body": "",
        }

        is_reply_msg, parent_id = is_reply(headers)

        assert is_reply_msg is True
        assert parent_id == "msg-with-brackets@example.com"
        assert "<" not in parent_id
        assert ">" not in parent_id

    def test_handles_references_as_string(self):
        """Should handle References header as whitespace-separated string."""
        headers = {
            "References": "<msg1@ex.com> <msg2@ex.com> <msg3@ex.com>",
            "body": "",
        }

        is_reply_msg, parent_id = is_reply(headers)

        assert is_reply_msg is True
        assert parent_id == "msg3@ex.com"  # Last in chain

    def test_handles_references_as_list(self):
        """Should handle References header as list."""
        headers = {
            "References": ["<msg1@ex.com>", "<msg2@ex.com>", "<msg3@ex.com>"],
            "body": "",
        }

        is_reply_msg, parent_id = is_reply(headers)

        assert is_reply_msg is True
        assert parent_id == "msg3@ex.com"

    def test_oe_token_case_insensitive(self):
        """OE token detection should be case insensitive."""
        headers = {
            "body": "Some text\n[OE-ABCD1234]\nMore text",
        }

        is_reply_msg, parent_id = is_reply(headers)

        assert is_reply_msg is True
        assert parent_id == "oe-token:abcd1234"


class TestLinkReplyToThread:
    """Tests for link_reply_to_thread() function."""

    def test_links_via_message_id(self, multi_event_db):
        """Should link reply to event using stored message_id."""
        parent_id = "orig-msg-001@venue.com"

        event_id = link_reply_to_thread(
            parent_id,
            multi_event_db["email_messages"],
            multi_event_db["thread_mappings"],
        )

        assert event_id == "evt-001"

    def test_links_via_thread_mapping(self, multi_event_db):
        """Should link reply using thread_mappings when message not found."""
        # Use a message ID that's in thread_mappings but not email_messages
        parent_id = "orig-msg-001@venue.com"

        # Clear email_messages to force thread_mapping lookup
        multi_event_db["email_messages"] = []

        event_id = link_reply_to_thread(
            parent_id,
            multi_event_db["email_messages"],
            multi_event_db["thread_mappings"],
        )

        assert event_id == "evt-001"

    def test_links_via_oe_token(self, multi_event_db):
        """Should link reply using OE token in thread_mappings."""
        # Add OE token mapping
        multi_event_db["thread_mappings"].append({
            "email_thread_id": "oe-token:evt001ab",
            "event_id": "evt-001",
        })

        event_id = link_reply_to_thread(
            "oe-token:evt001ab",
            multi_event_db["email_messages"],
            multi_event_db["thread_mappings"],
        )

        assert event_id == "evt-001"

    def test_returns_none_for_unknown_parent(self, multi_event_db):
        """Should return None when parent is not found."""
        event_id = link_reply_to_thread(
            "unknown-msg-id@example.com",
            multi_event_db["email_messages"],
            multi_event_db["thread_mappings"],
        )

        assert event_id is None

    def test_handles_empty_collections(self, empty_db):
        """Should handle empty collections gracefully."""
        event_id = link_reply_to_thread(
            "any-msg-id@example.com",
            empty_db["email_messages"],
            empty_db["thread_mappings"],
        )

        assert event_id is None


class TestStoreEmailMessage:
    """Tests for store_email_message() function."""

    def test_stores_new_message(self, empty_db):
        """Should store new message in email_messages."""
        store_email_message(
            empty_db,
            message_id="new-msg@example.com",
            from_address="client@example.com",
            resolved_event_id="evt-123",
        )

        assert len(empty_db["email_messages"]) == 1
        stored = empty_db["email_messages"][0]
        assert stored["message_id"] == "new-msg@example.com"
        assert stored["from_address"] == "client@example.com"
        assert stored["resolved_event_id"] == "evt-123"

    def test_stores_with_reply_headers(self, empty_db):
        """Should store message with In-Reply-To and References."""
        store_email_message(
            empty_db,
            message_id="reply@example.com",
            from_address="client@example.com",
            resolved_event_id="evt-123",
            in_reply_to="parent@example.com",
            references=["root@example.com", "parent@example.com"],
        )

        stored = empty_db["email_messages"][0]
        assert stored["in_reply_to"] == "parent@example.com"
        assert stored["references"] == ["root@example.com", "parent@example.com"]

    def test_avoids_duplicates(self, empty_db):
        """Should not create duplicate entries for same message_id."""
        store_email_message(
            empty_db,
            message_id="msg@example.com",
            from_address="client@example.com",
            resolved_event_id="evt-123",
        )
        store_email_message(
            empty_db,
            message_id="msg@example.com",  # Same ID
            from_address="client@example.com",
            resolved_event_id="evt-456",  # Different event
        )

        assert len(empty_db["email_messages"]) == 1

    def test_updates_unresolved_message(self, empty_db):
        """Should update resolved_event_id for existing unresolved message."""
        # Store without resolved_event_id
        empty_db["email_messages"].append({
            "message_id": "msg@example.com",
            "from_address": "client@example.com",
            "resolved_event_id": None,
        })

        store_email_message(
            empty_db,
            message_id="msg@example.com",
            from_address="client@example.com",
            resolved_event_id="evt-123",
        )

        assert len(empty_db["email_messages"]) == 1
        assert empty_db["email_messages"][0]["resolved_event_id"] == "evt-123"


class TestCreateThreadMapping:
    """Tests for create_thread_mapping() function."""

    def test_creates_mapping(self, empty_db):
        """Should create thread mapping."""
        create_thread_mapping(
            empty_db,
            email_thread_id="msg@example.com",
            event_id="evt-123",
        )

        assert len(empty_db["thread_mappings"]) == 1
        mapping = empty_db["thread_mappings"][0]
        assert mapping["email_thread_id"] == "msg@example.com"
        assert mapping["event_id"] == "evt-123"

    def test_avoids_duplicate_mappings(self, empty_db):
        """Should not create duplicate mappings for same thread_id."""
        create_thread_mapping(empty_db, "msg@example.com", "evt-123")
        create_thread_mapping(empty_db, "msg@example.com", "evt-456")

        assert len(empty_db["thread_mappings"]) == 1
        assert empty_db["thread_mappings"][0]["event_id"] == "evt-123"
