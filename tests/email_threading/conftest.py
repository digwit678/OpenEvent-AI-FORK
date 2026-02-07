"""Fixtures for email threading tests.

Provides multi-event database fixtures and mock LLM for testing
thread resolution scenarios.
"""
from __future__ import annotations

import pytest
from typing import Any, Dict, List
from unittest.mock import MagicMock


@pytest.fixture
def empty_db() -> Dict[str, Any]:
    """Empty database with threading collections initialized."""
    return {
        "events": [],
        "clients": {},
        "tasks": [],
        "email_messages": [],
        "event_signatures": [],
        "thread_mappings": [],
    }


@pytest.fixture
def multi_event_db() -> Dict[str, Any]:
    """Database with multiple events for same client.

    Used for testing thread resolution scenarios where a client
    has multiple ongoing or recent events.
    """
    return {
        "events": [
            {
                "event_id": "evt-001",
                "status": "Lead",
                "chosen_date": "15.03.2026",
                "date_confirmed": False,
                "current_step": 2,
                "created_at": "2026-01-15T10:00:00Z",
                "event_data": {
                    "Email": "sarah@corp.com",
                    "Name": "Sarah Johnson",
                    "Type of Event": "Workshop",
                    "Number of Participants": "25",
                },
            },
            {
                "event_id": "evt-002",
                "status": "Confirmed",
                "chosen_date": "10.01.2026",
                "date_confirmed": True,
                "current_step": 7,
                "created_at": "2025-12-01T10:00:00Z",
                "event_data": {
                    "Email": "sarah@corp.com",
                    "Name": "Sarah Johnson",
                    "Type of Event": "Conference",
                    "Number of Participants": "100",
                },
            },
            {
                "event_id": "evt-003",
                "status": "Lead",
                "chosen_date": "20.04.2026",
                "date_confirmed": False,
                "current_step": 1,
                "created_at": "2026-01-20T10:00:00Z",
                "event_data": {
                    "Email": "john@different.com",
                    "Name": "John Smith",
                    "Type of Event": "Meeting",
                    "Number of Participants": "10",
                },
            },
        ],
        "clients": {
            "sarah@corp.com": {
                "profile": {"name": "Sarah Johnson"},
                "history": [],
                "event_ids": ["evt-001", "evt-002"],
            },
            "john@different.com": {
                "profile": {"name": "John Smith"},
                "history": [],
                "event_ids": ["evt-003"],
            },
        },
        "tasks": [],
        "email_messages": [
            {
                "message_id": "orig-msg-001@venue.com",
                "from_address": "sarah@corp.com",
                "resolved_event_id": "evt-001",
                "in_reply_to": None,
                "references": [],
                "created_at": "2026-01-15T10:00:00Z",
            },
            {
                "message_id": "orig-msg-002@venue.com",
                "from_address": "sarah@corp.com",
                "resolved_event_id": "evt-002",
                "in_reply_to": None,
                "references": [],
                "created_at": "2025-12-01T10:00:00Z",
            },
        ],
        "event_signatures": [],
        "thread_mappings": [
            {
                "email_thread_id": "orig-msg-001@venue.com",
                "event_id": "evt-001",
                "created_at": "2026-01-15T10:00:00Z",
            },
        ],
    }


@pytest.fixture
def mock_llm(monkeypatch):
    """Mock LLM for deterministic resolver tests.

    Usage:
        mock_llm["result"] = {"decision": "attach", "event_id": "evt-001", "confidence": 0.9}
        resolver.resolve(...)
    """
    responses: Dict[str, Any] = {}

    def mock_complete(
        prompt: str,
        *,
        system_prompt: str = None,
        temperature: float = 0.1,
        max_tokens: int = 1000,
        json_mode: bool = False,
    ) -> str:
        import json
        result = responses.get("result", {"decision": "new_event", "confidence": 1.0, "reason": "mock_default"})
        return json.dumps(result)

    # Patch the agent adapter's complete method
    mock_agent = MagicMock()
    mock_agent.complete = mock_complete

    monkeypatch.setattr(
        "adapters.agent_adapter.get_agent_adapter",
        lambda: mock_agent
    )

    return responses


@pytest.fixture
def email_with_reply_headers() -> Dict[str, Any]:
    """Email payload with In-Reply-To header (reply to evt-001)."""
    return {
        "msg_id": "reply-msg-001@client.com",
        "from_email": "sarah@corp.com",
        "from_name": "Sarah Johnson",
        "subject": "Re: Your workshop booking",
        "body": "Sounds good, let's proceed with March 15th.",
        "headers": {
            "Message-ID": "<reply-msg-001@client.com>",
            "In-Reply-To": "<orig-msg-001@venue.com>",
            "References": "<orig-msg-001@venue.com>",
        },
    }


@pytest.fixture
def email_with_references_chain() -> Dict[str, Any]:
    """Email payload with References header chain."""
    return {
        "msg_id": "chain-msg-003@client.com",
        "from_email": "sarah@corp.com",
        "from_name": "Sarah Johnson",
        "subject": "Re: Re: Your workshop booking",
        "body": "Just confirming we need 30 chairs.",
        "headers": {
            "Message-ID": "<chain-msg-003@client.com>",
            "In-Reply-To": "<chain-msg-002@venue.com>",
            "References": "<orig-msg-001@venue.com> <chain-msg-002@venue.com>",
        },
    }


@pytest.fixture
def email_with_oe_token() -> Dict[str, Any]:
    """Email payload with explicit OE token in footer."""
    return {
        "msg_id": "token-msg-001@client.com",
        "from_email": "sarah@corp.com",
        "from_name": "Sarah Johnson",
        "subject": "Question about my booking",
        "body": """Hi,

I have a question about catering options.

Best,
Sarah

---
[OE-evt001ab]
""",
        "headers": {
            "Message-ID": "<token-msg-001@client.com>",
        },
    }


@pytest.fixture
def new_email_same_event_details() -> Dict[str, Any]:
    """New email (no reply headers) about the March 15 workshop."""
    return {
        "msg_id": "new-msg-001@client.com",
        "from_email": "sarah@corp.com",
        "from_name": "Sarah Johnson",
        "subject": "March workshop - equipment question",
        "body": "For our March 15 workshop with 25 people, do you have projectors available?",
        "headers": {
            "Message-ID": "<new-msg-001@client.com>",
        },
    }


@pytest.fixture
def new_email_different_event() -> Dict[str, Any]:
    """New email (no reply headers) about a completely different event."""
    return {
        "msg_id": "new-msg-002@client.com",
        "from_email": "sarah@corp.com",
        "from_name": "Sarah Johnson",
        "subject": "New booking request for June",
        "body": "Hi, I'd like to book a dinner for 50 guests on June 20th.",
        "headers": {
            "Message-ID": "<new-msg-002@client.com>",
        },
    }


@pytest.fixture
def ambiguous_email() -> Dict[str, Any]:
    """Ambiguous email that could match any event."""
    return {
        "msg_id": "ambiguous-msg-001@client.com",
        "from_email": "sarah@corp.com",
        "from_name": "Sarah Johnson",
        "subject": "Quick question",
        "body": "Do you have parking available?",
        "headers": {
            "Message-ID": "<ambiguous-msg-001@client.com>",
        },
    }
