"""
Shared fixtures for E2E comprehensive tests.

These fixtures provide:
- True E2E test harness calling process_msg directly
- Event state builders at specific workflow steps
- Mock calendar availability
- Detection result builders
- Assertion helpers for fallback/stub detection

TRUE E2E: Tests in this module call the full workflow pipeline via process_msg,
not just individual handlers or detection functions. This ensures tests match
what would happen in Playwright/real user sessions.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from importlib import import_module
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest

from workflow_email import process_msg
from workflows.common.types import IncomingMessage, WorkflowState
from workflows.io import database as db_io


# =============================================================================
# FALLBACK DETECTION PATTERNS
# =============================================================================

FALLBACK_PATTERNS = [
    "Thanks for your message",
    "Thank you for your message",
    "I'll look into",
    "Let me check",
    "no specific information available",
    "I don't have information",
    "Unable to process",
    "generic response",
    "empty_reply_fallback",  # Internal fallback marker
    "I'm processing your request",  # WF0.1 fallback guard
]

# Patterns that indicate a stub/mock response
STUB_RESPONSE_PATTERNS = [
    "[STUB]",
    "stub response",
    "test response",
]


# =============================================================================
# STEP CONFIGURATIONS
# =============================================================================

STEP_NAMES = {
    2: "Date Confirmation",
    3: "Room Availability",
    4: "Offer/Products",
    5: "Negotiation",
    6: "Billing/Deposit",
    7: "Confirmation",
}

# What gates are typically passed by each step
STEP_PREREQUISITES = {
    2: {"date_confirmed": False},
    3: {"date_confirmed": True, "locked_room_id": None},
    4: {"date_confirmed": True, "locked_room_id": "Room A"},
    5: {"date_confirmed": True, "locked_room_id": "Room A", "offer_sent": True},
    6: {"date_confirmed": True, "locked_room_id": "Room A", "offer_sent": True, "offer_accepted": True},
    7: {"date_confirmed": True, "locked_room_id": "Room A", "offer_sent": True, "offer_accepted": True, "billing_captured": True},
}


# =============================================================================
# E2E TEST HARNESS
# =============================================================================


class E2ETestHarness:
    """
    True E2E test harness that calls process_msg for full workflow execution.

    This harness:
    - Creates a temporary DB with an event at a specific step
    - Calls process_msg (the full workflow entry point)
    - Verifies draft messages, step transitions, and response quality
    - Checks for fallback patterns
    """

    def __init__(self, tmp_path: Path, event_entry: Dict[str, Any], client_email: str = "client@example.com"):
        self.tmp_path = tmp_path
        self.db_path = tmp_path / f"events_{uuid.uuid4().hex[:8]}.json"
        self.client_email = client_email
        self.thread_id = f"thread-{uuid.uuid4().hex[:8]}"
        self.msg_counter = 0
        self.last_result: Optional[Dict[str, Any]] = None
        self.event_entry = event_entry
        self._original_patches: List[Tuple[Any, str, Any]] = []

        # Initialize DB with event and client
        self._init_db()
        self._install_stubs()

    def _init_db(self) -> None:
        """Initialize the database with the event entry."""
        # Add client email to event for lookup
        self.event_entry["client_email"] = self.client_email
        self.event_entry.setdefault("event_data", {})["Email"] = self.client_email
        self.event_entry.setdefault("created_at", datetime.utcnow().isoformat() + "Z")

        db = {
            "events": [self.event_entry],
            "clients": {
                self.client_email: {
                    "email": self.client_email,
                    "history": [],
                    "profile": {"name": "Test Client"},
                }
            },
        }
        db_io.save_db(db, self.db_path)

    def _install_stubs(self) -> None:
        """Install stubs for deterministic testing (dates, rooms)."""
        # Import stubs
        try:
            from tests.stubs.dates_and_rooms import (
                suggest_dates as stub_suggest_dates,
                load_rooms_config as stub_load_rooms_config,
                week_window as stub_week_window,
            )
        except ImportError:
            return  # Stubs not available

        # Patch date suggestion
        modules_to_patch = [
            "backend.workflows.steps.step1_intake.condition.checks",
            "backend.workflows.steps.step1_intake.condition",
            "backend.workflows.steps.step1_intake",
            "backend.workflows.steps.step2_date_confirmation.trigger.step2_handler",
        ]
        for name in modules_to_patch:
            try:
                module = import_module(name)
                if hasattr(module, "suggest_dates"):
                    original = getattr(module, "suggest_dates")
                    self._original_patches.append((module, "suggest_dates", original))
                    setattr(module, "suggest_dates", stub_suggest_dates)
            except (ImportError, ModuleNotFoundError):
                pass

        # Patch week_window
        try:
            dates_module = import_module("utils.dates")
            original_week_window = getattr(dates_module, "week_window")
            self._original_patches.append((dates_module, "week_window", original_week_window))
            setattr(dates_module, "week_window", stub_week_window)
        except (ImportError, ModuleNotFoundError, AttributeError):
            pass

        # Patch room config
        try:
            room_config_module = import_module("workflows.steps.step3_room_availability.db_pers")
            original_load_rooms = getattr(room_config_module, "load_rooms_config")
            self._original_patches.append((room_config_module, "load_rooms_config", original_load_rooms))
            setattr(room_config_module, "load_rooms_config", stub_load_rooms_config)
        except (ImportError, ModuleNotFoundError, AttributeError):
            pass

        try:
            ranking_module = import_module("rooms.ranking")
            original_ranking_load = getattr(ranking_module, "load_rooms_config")
            self._original_patches.append((ranking_module, "load_rooms_config", original_ranking_load))
            setattr(ranking_module, "load_rooms_config", stub_load_rooms_config)
        except (ImportError, ModuleNotFoundError, AttributeError):
            pass

    def close(self) -> None:
        """Restore original patches."""
        while self._original_patches:
            module, attr, original = self._original_patches.pop()
            setattr(module, attr, original)

    def send_message(self, body: str, subject: str = "Re: Event Booking") -> Dict[str, Any]:
        """Send a message through the full workflow and return the result."""
        self.msg_counter += 1
        payload = {
            "msg_id": f"msg-{self.msg_counter}",
            "from_name": "Test Client",
            "from_email": self.client_email,
            "subject": subject,
            "body": body,
            "ts": datetime.utcnow().isoformat() + "Z",
            "thread_id": self.thread_id,
        }

        self.last_result = process_msg(payload, db_path=self.db_path)
        return self.last_result

    def get_current_event(self) -> Optional[Dict[str, Any]]:
        """Get the current event from the database."""
        db = db_io.load_db(self.db_path)
        events = db.get("events", [])
        return events[-1] if events else None

    def get_draft_messages(self) -> List[Dict[str, Any]]:
        """Get draft messages from the last result."""
        if not self.last_result:
            return []
        return self.last_result.get("draft_messages", [])

    def get_combined_body(self) -> str:
        """Get combined body text from all draft messages."""
        drafts = self.get_draft_messages()
        bodies = []
        for draft in drafts:
            if body := draft.get("body_markdown") or draft.get("body"):
                bodies.append(body)
        return "\n\n".join(bodies)

    def assert_no_fallback(self, context: str = "") -> None:
        """Assert no fallback patterns in response."""
        body = self.get_combined_body()
        body_lower = body.lower()

        for pattern in FALLBACK_PATTERNS:
            if pattern.lower() in body_lower:
                ctx = f" ({context})" if context else ""
                raise AssertionError(
                    f"Fallback pattern detected{ctx}: '{pattern}' found in response:\n{body[:500]}"
                )

        # Also check _fallback_reason in drafts
        for draft in self.get_draft_messages():
            if "_fallback_reason" in draft:
                raise AssertionError(
                    f"Draft has _fallback_reason: {draft['_fallback_reason']}"
                )

    def assert_step_transition(self, from_step: int, to_step: int) -> None:
        """Assert that a step transition occurred."""
        event = self.get_current_event()
        if not event:
            raise AssertionError("No event found in database")

        current_step = event.get("current_step")
        if current_step != to_step:
            raise AssertionError(
                f"Expected step transition {from_step} → {to_step}, but current_step is {current_step}"
            )

    def assert_step_unchanged(self, expected_step: int) -> None:
        """Assert that the step has not changed."""
        event = self.get_current_event()
        if not event:
            raise AssertionError("No event found in database")

        current_step = event.get("current_step")
        if current_step != expected_step:
            raise AssertionError(
                f"Step should remain {expected_step}, but changed to {current_step}"
            )

    def assert_caller_step_set(self, expected_caller: int) -> None:
        """Assert caller_step is correctly set for detour return."""
        event = self.get_current_event()
        if not event:
            raise AssertionError("No event found in database")

        caller_step = event.get("caller_step")
        if caller_step != expected_caller:
            raise AssertionError(
                f"Expected caller_step={expected_caller}, got {caller_step}"
            )

    def assert_has_draft_message(self) -> None:
        """Assert that at least one draft message was generated."""
        drafts = self.get_draft_messages()
        if not drafts:
            raise AssertionError("No draft messages generated")

    def assert_body_contains(self, *phrases: str) -> None:
        """Assert the response body contains all specified phrases."""
        body = self.get_combined_body().lower()
        for phrase in phrases:
            if phrase.lower() not in body:
                raise AssertionError(
                    f"Expected phrase '{phrase}' not found in response:\n{body[:500]}"
                )

    def assert_body_not_contains(self, *phrases: str) -> None:
        """Assert the response body does not contain specified phrases."""
        body = self.get_combined_body().lower()
        for phrase in phrases:
            if phrase.lower() in body:
                raise AssertionError(
                    f"Unexpected phrase '{phrase}' found in response"
                )


@pytest.fixture
def e2e_harness(tmp_path, build_event_entry):
    """Factory for creating E2E test harnesses."""
    harnesses: List[E2ETestHarness] = []

    def _create(
        current_step: int,
        *,
        event_kwargs: Optional[Dict[str, Any]] = None,
        client_email: str = "client@example.com",
    ) -> E2ETestHarness:
        """
        Create an E2E test harness with an event at the specified step.

        Args:
            current_step: The workflow step to start at (2-7)
            event_kwargs: Additional kwargs for build_event_entry
            client_email: Client email address
        """
        event_kwargs = event_kwargs or {}
        event_entry = build_event_entry(current_step, **event_kwargs)
        harness = E2ETestHarness(tmp_path, event_entry, client_email)
        harnesses.append(harness)
        return harness

    yield _create

    # Cleanup
    for harness in harnesses:
        harness.close()


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def build_message():
    """Factory for creating IncomingMessage objects."""

    def _build(body: str, subject: str = "Test Email", from_email: str = "client@example.com") -> IncomingMessage:
        return IncomingMessage(
            msg_id=f"msg-{datetime.utcnow().timestamp()}",
            from_name="Test Client",
            from_email=from_email,
            subject=subject,
            body=body,
            ts=datetime.utcnow().isoformat() + "Z",
        )

    return _build


@pytest.fixture
def build_event_entry():
    """Factory for creating event entries at specific workflow steps."""

    def _build(
        current_step: int,
        *,
        event_id: str = "EVT-TEST-001",
        chosen_date: Optional[str] = "15.03.2026",
        date_confirmed: bool = True,
        locked_room_id: Optional[str] = "Room A",
        requirements: Optional[Dict[str, Any]] = None,
        requirements_hash: Optional[str] = None,
        room_eval_hash: Optional[str] = None,
        caller_step: Optional[int] = None,
        offer_sent: bool = False,
        offer_accepted: bool = False,
        billing_captured: bool = False,
        deposit_paid: bool = False,
        **extra_fields,
    ) -> Dict[str, Any]:
        """
        Build an event entry at a specific step with appropriate state.

        Args:
            current_step: The workflow step (2-7)
            event_id: Event identifier
            chosen_date: The confirmed date (DD.MM.YYYY format)
            date_confirmed: Whether date is confirmed
            locked_room_id: The selected room
            requirements: Event requirements dict
            requirements_hash: Hash of requirements for caching
            room_eval_hash: Hash used for room evaluation caching
            caller_step: For detour tracking
            offer_sent: Whether offer has been sent
            offer_accepted: Whether offer was accepted
            billing_captured: Whether billing info captured
            deposit_paid: Whether deposit is paid
            **extra_fields: Additional fields to include
        """
        if requirements is None:
            requirements = {
                "number_of_participants": 30,
                "seating_layout": "dinner",
                "event_duration": {"start": "18:00", "end": "23:00"},
            }

        if requirements_hash is None:
            requirements_hash = hashlib.sha256(str(requirements).encode()).hexdigest()[:16]

        # Set room_eval_hash to match requirements_hash by default (no re-eval needed)
        if room_eval_hash is None and current_step >= 3:
            room_eval_hash = requirements_hash

        # Build ISO date from DD.MM.YYYY format
        chosen_date_iso = None
        if chosen_date and date_confirmed:
            try:
                parts = chosen_date.split(".")
                if len(parts) == 3:
                    chosen_date_iso = f"{parts[2]}-{parts[1]}-{parts[0]}"
            except Exception:
                pass

        entry = {
            "event_id": event_id,
            "current_step": current_step,
            "thread_state": "Awaiting Client",
            "chosen_date": chosen_date if date_confirmed else None,
            "chosen_date_iso": chosen_date_iso,
            "date_confirmed": date_confirmed,
            "locked_room_id": locked_room_id if current_step >= 4 else None,
            "requirements": requirements,
            "requirements_hash": requirements_hash,
            "room_eval_hash": room_eval_hash,
            "caller_step": caller_step,
            "preferences": {"wish_products": [], "keywords": []},
            "selected_products": [],
            "products_state": {"line_items": []},
            "offer_sent": offer_sent,
            "offer_accepted": offer_accepted,
            "billing_address": {} if not billing_captured else {"company": "ACME AG", "city": "Zurich"},
            "billing_captured": billing_captured,
            "deposit_paid": deposit_paid,
            "site_visit_state": {},
            # Required for workflow routing
            "event_data": {
                "Status": "Option" if current_step >= 4 else "Inquiry",
            },
            "requested_window": {
                "date_iso": chosen_date_iso,
                "display_date": chosen_date if date_confirmed else None,
                "start_time": "18:00",
                "end_time": "23:00",
            } if date_confirmed else None,
            "audit": [],
        }

        # Apply step-appropriate defaults
        if current_step >= 4:
            entry["locked_room_id"] = locked_room_id or "Room A"
        if current_step >= 5:
            entry["offer_sent"] = True
        if current_step >= 6:
            entry["offer_accepted"] = True
        if current_step >= 7:
            entry["billing_captured"] = True

        entry.update(extra_fields)
        return entry

    return _build


@pytest.fixture
def build_state(tmp_path, build_message, build_event_entry):
    """Factory for creating WorkflowState at a specific step."""

    def _build(
        current_step: int,
        message_body: str,
        *,
        event_kwargs: Optional[Dict[str, Any]] = None,
        user_info: Optional[Dict[str, Any]] = None,
    ) -> WorkflowState:
        """
        Build a WorkflowState positioned at a specific step.

        Args:
            current_step: The workflow step (2-7)
            message_body: The incoming message text
            event_kwargs: Additional kwargs for build_event_entry
            user_info: Pre-populated user_info dict
        """
        message = build_message(message_body)
        event_kwargs = event_kwargs or {}
        event_entry = build_event_entry(current_step, **event_kwargs)

        state = WorkflowState(
            message=message,
            db_path=tmp_path / "events.json",
            db={"events": [event_entry]},
        )
        state.event_id = event_entry["event_id"]
        state.event_entry = event_entry
        state.current_step = current_step
        state.caller_step = event_entry.get("caller_step")
        state.thread_state = "Awaiting Client"
        state.user_info = user_info or {}

        return state

    return _build


@pytest.fixture
def mock_room_availability(monkeypatch):
    """Mock calendar to control room availability for specific dates."""

    def _mock(availability_map: Dict[str, Dict[str, str]]):
        """
        Set up room availability mock.

        Args:
            availability_map: Dict of date -> {room -> status}
                Example: {"15.03.2026": {"Room A": "Available", "Room B": "Option"}}
        """
        def fake_room_status(db, date_str, room_name):
            date_avail = availability_map.get(date_str, {})
            return date_avail.get(room_name, "Unavailable")

        # Import and patch the actual module
        try:
            from workflows.steps.step3_room_availability.trigger import step3_handler
            monkeypatch.setattr(step3_handler, "room_status_on_date", fake_room_status)
        except (ImportError, AttributeError):
            pass  # Module structure may vary

    return _mock


@pytest.fixture
def assert_no_fallback():
    """Assert response contains no fallback/stub messages."""

    def _assert(text: str, context: str = ""):
        """
        Assert text contains no fallback patterns.

        Args:
            text: The response text to check
            context: Additional context for error message
        """
        text_lower = text.lower()
        for pattern in FALLBACK_PATTERNS:
            if pattern.lower() in text_lower:
                ctx = f" ({context})" if context else ""
                raise AssertionError(f"Fallback pattern detected{ctx}: '{pattern}' found in response")

    return _assert


@pytest.fixture
def assert_step_unchanged():
    """Assert workflow step was not changed by a Q&A or other non-routing action."""

    def _assert(state: WorkflowState, expected_step: int):
        """
        Assert current_step remains at expected value.

        Args:
            state: The WorkflowState to check
            expected_step: The step number that should be current
        """
        # Check state.current_step
        if state.current_step != expected_step:
            raise AssertionError(
                f"Step changed unexpectedly: expected {expected_step}, got {state.current_step}"
            )

        # Check event_entry if present
        if state.event_entry:
            entry_step = state.event_entry.get("current_step")
            if entry_step is not None and entry_step != expected_step:
                raise AssertionError(
                    f"Event entry step changed: expected {expected_step}, got {entry_step}"
                )

    return _assert


@pytest.fixture
def assert_detour_routing():
    """Assert detour was routed correctly per DAG rules."""

    def _assert(
        state: WorkflowState,
        *,
        expected_next_step: int,
        expected_caller_step: int,
        original_step: int,
    ):
        """
        Assert detour routing is correct.

        Args:
            state: The WorkflowState after detour processing
            expected_next_step: Where the detour should route to
            expected_caller_step: The caller_step that should be preserved
            original_step: The step we detoured from
        """
        # Check caller_step is preserved
        caller = state.caller_step or state.event_entry.get("caller_step")
        if caller != expected_caller_step:
            raise AssertionError(
                f"caller_step incorrect: expected {expected_caller_step}, got {caller}"
            )

        # If draft messages exist, check the step in the last one
        if state.draft_messages:
            draft_step = state.draft_messages[-1].get("step")
            if draft_step is not None:
                draft_step_int = int(str(draft_step).split(".")[0])  # Handle "2.1" format
                if draft_step_int != expected_next_step:
                    raise AssertionError(
                        f"Draft routed to wrong step: expected {expected_next_step}, got {draft_step_int}"
                    )

    return _assert


# =============================================================================
# DETECTION RESULT HELPERS
# =============================================================================


@dataclass
class MockDetectionResult:
    """Mock detection result for testing."""
    intent: str = "general_qna"
    is_change_request: bool = False
    is_question: bool = False
    is_confirmation: bool = False
    is_acceptance: bool = False
    date: Optional[str] = None
    participants: Optional[int] = None
    room_preference: Optional[str] = None
    products: List[str] = field(default_factory=list)
    qna_types: List[str] = field(default_factory=list)
    billing_address: Optional[Dict[str, str]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent,
            "signals": {
                "change_request": self.is_change_request,
                "question": self.is_question,
                "confirmation": self.is_confirmation,
                "acceptance": self.is_acceptance,
            },
            "entities": {
                "date": self.date,
                "participants": self.participants,
                "room_preference": self.room_preference,
                "products": self.products,
                "billing_address": self.billing_address,
            },
            "qna_types": self.qna_types,
        }


@pytest.fixture
def detection_result_factory():
    """Factory for creating mock detection results."""

    def _create(**kwargs) -> MockDetectionResult:
        return MockDetectionResult(**kwargs)

    return _create


# =============================================================================
# Q&A TYPE DEFINITIONS
# =============================================================================

QNA_TYPES = {
    "rooms_by_feature": {
        "messages": [
            "Does Room A have a projector?",
            "Which rooms have a terrace?",
            "Is there a room with natural light?",
        ],
        "expected_qna_type": "rooms_by_feature",
    },
    "catering_for": {
        "messages": [
            "What menus do you offer?",
            "Can you accommodate vegan guests?",
            "What catering options are available?",
        ],
        "expected_qna_type": "catering_for",
    },
    "parking_policy": {
        "messages": [
            "Where can guests park?",
            "Is parking included?",
            "How much is parking?",
        ],
        "expected_qna_type": "parking_policy",
    },
    "free_dates": {
        "messages": [
            "Which dates are available in February?",
            "What rooms are free next weekend?",
            "Do you have availability on March 15?",
        ],
        "expected_qna_type": "free_dates",
    },
    "site_visit_overview": {
        "messages": [
            "Do you offer venue tours?",
            "Can we visit the space before booking?",
            "Is a site visit possible?",
        ],
        "expected_qna_type": "site_visit_overview",
    },
    "room_features": {
        "messages": [
            "What features does Room B have?",
            "Tell me about Room A's capacity",
            "What equipment is in the main room?",
        ],
        "expected_qna_type": "room_features",
    },
}


@pytest.fixture
def qna_test_cases():
    """Provide Q&A test case definitions."""
    return QNA_TYPES


# =============================================================================
# DETOUR DEFINITIONS
# =============================================================================

DETOUR_CONFIGS = {
    "date": {
        "trigger_message": "Can we change the date to March 20?",
        "routes_to_step": 2,
        "valid_from_steps": [3, 4, 5, 6, 7],
        "user_info_updates": {"date": "2026-03-20"},
    },
    "room": {
        "trigger_message": "Can we switch to Room B instead?",
        "routes_to_step": 3,
        "valid_from_steps": [2, 4, 5, 6, 7],
        "user_info_updates": {"room": "Room B"},
    },
    "participants": {
        "trigger_message": "Actually we're expecting 50 people now",
        "routes_to_step": 3,
        "valid_from_steps": [2, 3, 4, 5, 6, 7],
        "user_info_updates": {"participants": 50},
    },
    "billing": {
        "trigger_message": "Billing address: ACME AG, Bahnhofstrasse 1, Zurich",
        "routes_to_step": None,  # In-place, no routing
        "valid_from_steps": [2, 3, 4, 5, 6, 7],
        "user_info_updates": {"billing_address": {"company": "ACME AG", "city": "Zurich"}},
    },
    "products": {
        "trigger_message": "Please add a projector to the booking",
        "routes_to_step": 4,
        "valid_from_steps": [4, 5, 6, 7],
        "user_info_updates": {"products_add": ["Projector"]},
    },
}


@pytest.fixture
def detour_test_configs():
    """Provide detour test configurations."""
    return DETOUR_CONFIGS
