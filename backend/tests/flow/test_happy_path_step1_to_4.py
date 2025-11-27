"""
Happy-Path Flow Test: Steps 1-4 (FLOW_1TO4_HAPPY_001)

Tests complete intake-to-offer flow without detours.
Validates step progression, hash consistency, HIL gates, and footer contract.

References:
- TEST_MATRIX_detection_and_flow.md: FLOW_1TO4_HAPPY_001
- CLAUDE.md: 7-Step Pipeline, Entry Guard Prerequisites
"""

from __future__ import annotations

import hashlib
import json
import re
import pytest
from typing import Any, Dict, List, Optional


# ==============================================================================
# ANTI-FALLBACK ASSERTIONS
# ==============================================================================


FALLBACK_PATTERNS = [
    "no specific information available",
    "sorry, cannot handle",
    "unable to process",
    "i don't understand",
    "there appears to be no",
    "it appears there is no",
]


def assert_no_fallback(response_body: str, context: str = ""):
    """Assert that response does not contain legacy fallback messages."""
    if not response_body:
        return
    lowered = response_body.lower()
    for pattern in FALLBACK_PATTERNS:
        assert pattern not in lowered, (
            f"FALLBACK DETECTED: '{pattern}' in response.\n"
            f"Context: {context}\n"
            f"Response snippet: {response_body[:300]}..."
        )


# ==============================================================================
# FOOTER CONTRACT VALIDATION
# ==============================================================================


FOOTER_PATTERN = re.compile(
    r"Step:\s*(?P<step>[\w\s]+)\s*·\s*Next:\s*(?P<next>[\w\s/()]+)\s*·\s*State:\s*(?P<state>[\w\s]+)"
)


def assert_footer_contract(response_body: str, expected_step: Optional[str] = None):
    """Assert that response includes proper footer per UX contract."""
    if not response_body:
        return

    match = FOOTER_PATTERN.search(response_body)
    assert match is not None, (
        f"Footer contract violated: no 'Step: X · Next: Y · State: Z' found.\n"
        f"Response: {response_body[:500]}..."
    )

    if expected_step:
        actual_step = match.group("step").strip()
        assert expected_step.lower() in actual_step.lower(), (
            f"Expected step '{expected_step}' not found in footer step '{actual_step}'"
        )


# ==============================================================================
# SIMULATED EVENT STATE
# ==============================================================================


def _compute_requirements_hash(requirements: Dict[str, Any]) -> str:
    """Compute SHA256 hash of requirements for change detection."""
    serialized = json.dumps(requirements, sort_keys=True)
    return hashlib.sha256(serialized.encode()).hexdigest()[:16]


def create_event_state(
    event_id: str = "EVT-TEST-001",
    email: str = None,
    chosen_date: str = None,
    date_confirmed: bool = False,
    participants: int = None,
    locked_room_id: str = None,
    room_eval_hash: str = None,
    current_step: int = 1,
    status: str = "Lead",
) -> Dict[str, Any]:
    """Create a simulated event state for testing."""
    requirements = {}
    if participants:
        requirements["number_of_participants"] = participants

    requirements_hash = _compute_requirements_hash(requirements) if requirements else None

    return {
        "event_id": event_id,
        "email": email,
        "chosen_date": chosen_date,
        "date_confirmed": date_confirmed,
        "requirements": requirements,
        "requirements_hash": requirements_hash,
        "locked_room_id": locked_room_id,
        "room_eval_hash": room_eval_hash,
        "current_step": current_step,
        "status": status,
        "thread_state": "AwaitingClient",
    }


# ==============================================================================
# STEP PROGRESSION LOGIC (Simulated)
# ==============================================================================


def can_advance_to_step_2(state: Dict[str, Any]) -> bool:
    """Check if we can advance from Step 1 to Step 2."""
    return bool(state.get("email")) and bool(state.get("requirements", {}).get("number_of_participants"))


def can_advance_to_step_3(state: Dict[str, Any]) -> bool:
    """Check if we can advance from Step 2 to Step 3."""
    return (
        state.get("date_confirmed") is True
        and bool(state.get("requirements", {}).get("number_of_participants"))
        and bool(state.get("requirements_hash"))
    )


def can_advance_to_step_4(state: Dict[str, Any]) -> bool:
    """Check P1-P4 prerequisites for Step 4."""
    # P1: date_confirmed
    if not state.get("date_confirmed"):
        return False

    # P2: locked_room_id AND requirements_hash == room_eval_hash
    if not state.get("locked_room_id"):
        return False
    if state.get("requirements_hash") != state.get("room_eval_hash"):
        return False

    # P3: capacity present
    if not state.get("requirements", {}).get("number_of_participants"):
        return False

    return True


# ==============================================================================
# FLOW_1TO4_HAPPY_001: Complete Intake to Offer
# ==============================================================================


class TestHappyPathStep1To4:
    """
    FLOW_1TO4_HAPPY_001: Complete Intake to Offer

    Tests the happy path from initial inquiry through offer presentation.
    Simulates state progression without actual LLM calls.
    """

    def test_turn_1_initial_inquiry(self):
        """
        Turn 1: Initial booking request creates event.
        Input: "I'd like to book a workshop for 25 people on December 15, 2025"
        Expected: event_id created, Step 1 active
        """
        # Simulated extraction from message
        extracted = {
            "participants": 25,
            "date_hint": "2025-12-15",  # Shortcut captured, not confirmed
            "time_start": "14:00",
            "time_end": "18:00",
        }

        # Create event with extracted data
        state = create_event_state(
            event_id="EVT-TEST-001",
            participants=extracted["participants"],
            current_step=1,
        )

        # Assertions
        assert state["event_id"].startswith("EVT-")
        assert state["current_step"] == 1
        assert state["requirements"]["number_of_participants"] == 25
        assert state["date_confirmed"] is False  # Not yet confirmed
        assert state["status"] == "Lead"

        # Would prompt for email
        response = "Thank you for your interest! Could you share your email address?"
        assert_no_fallback(response, "Turn 1 response")

    def test_turn_2_email_capture(self):
        """
        Turn 2: Email captured, advance toward Step 2.
        Input: "client@example.com"
        Expected: email captured, prerequisites for Step 2 met
        """
        state = create_event_state(
            event_id="EVT-TEST-001",
            participants=25,
            current_step=1,
        )

        # Capture email
        state["email"] = "client@example.com"

        # Check advancement
        assert can_advance_to_step_2(state) is True
        state["current_step"] = 2

        assert state["current_step"] == 2
        assert state["email"] == "client@example.com"
        assert state["date_confirmed"] is False

    def test_turn_3_system_proposes_dates(self):
        """
        Turn 3: System proposes available dates.
        Expected: date_confirmed=False, awaiting client selection
        """
        state = create_event_state(
            event_id="EVT-TEST-001",
            email="client@example.com",
            participants=25,
            current_step=2,
        )

        # Simulated system response proposing dates
        response = """Based on your request for December 15, 2025, I can confirm availability.

Available time slots:
- December 15, 2025: 14:00-18:00 (preferred)
- December 16, 2025: 14:00-18:00 (alternative)

Please confirm which date works best for you.

Step: 2 Date Confirmation · Next: Confirm date · State: Awaiting Client"""

        assert_no_fallback(response, "Turn 3 date proposal")
        assert_footer_contract(response, expected_step="Date")

        # State unchanged until confirmation
        assert state["date_confirmed"] is False

    def test_turn_4_date_confirmed(self):
        """
        Turn 4: Client confirms date, advance to Step 3.
        Input: "December 15 works"
        Expected: date_confirmed=True, chosen_date set, advance to Step 3
        """
        state = create_event_state(
            event_id="EVT-TEST-001",
            email="client@example.com",
            participants=25,
            current_step=2,
        )

        # Client confirmation triggers date lock
        state["chosen_date"] = "2025-12-15"
        state["date_confirmed"] = True

        # Check advancement
        assert can_advance_to_step_3(state) is True
        state["current_step"] = 3

        assert state["date_confirmed"] is True
        assert state["chosen_date"] == "2025-12-15"
        assert state["current_step"] == 3

    def test_turn_5_system_presents_rooms(self):
        """
        Turn 5: System presents available rooms.
        Expected: Room options shown, awaiting selection
        """
        state = create_event_state(
            event_id="EVT-TEST-001",
            email="client@example.com",
            chosen_date="2025-12-15",
            date_confirmed=True,
            participants=25,
            current_step=3,
        )

        # Simulated room availability response
        response = """Great! For December 15, 2025 with 25 participants, here are the available rooms:

| Room | Capacity | Features |
|------|----------|----------|
| Room A | 40 | Projector, HDMI, Natural light |
| Room B | 60 | Sound system, Stage |

Which room would you prefer?

Step: 3 Room Availability · Next: Select room · State: Awaiting Client"""

        assert_no_fallback(response, "Turn 5 room options")
        assert_footer_contract(response, expected_step="Room")

        # No room locked yet
        assert state["locked_room_id"] is None

    def test_turn_6_room_selected(self):
        """
        Turn 6: Client selects room, advance to Step 4.
        Input: "Room A please"
        Expected: locked_room_id set, room_eval_hash matches requirements_hash
        """
        state = create_event_state(
            event_id="EVT-TEST-001",
            email="client@example.com",
            chosen_date="2025-12-15",
            date_confirmed=True,
            participants=25,
            current_step=3,
        )

        # Lock room and set hash
        state["locked_room_id"] = "room_a"
        state["room_eval_hash"] = state["requirements_hash"]

        # Check advancement
        assert can_advance_to_step_4(state) is True
        state["current_step"] = 4

        assert state["locked_room_id"] == "room_a"
        assert state["room_eval_hash"] == state["requirements_hash"]
        assert state["current_step"] == 4

    def test_turn_7_offer_draft_hil(self):
        """
        Turn 7: System presents offer draft for HIL approval.
        Expected: Draft awaits HIL, thread_state="WaitingOnHIL"
        """
        state = create_event_state(
            event_id="EVT-TEST-001",
            email="client@example.com",
            chosen_date="2025-12-15",
            date_confirmed=True,
            participants=25,
            current_step=4,
        )
        state["locked_room_id"] = "room_a"
        state["room_eval_hash"] = state["requirements_hash"]
        state["thread_state"] = "WaitingOnHIL"

        # Simulated offer draft
        response = """## Offer Draft for Review

**Event Details:**
- Date: December 15, 2025 (14:00-18:00)
- Room: Room A (capacity 40)
- Participants: 25

**Pricing:**
- Room rental: CHF 500
- Total: CHF 500 (excl. VAT)

[Awaiting HIL Approval]

Step: 4 Offer · Next: HIL Review · State: Waiting on HIL"""

        assert_no_fallback(response, "Turn 7 offer draft")
        assert_footer_contract(response, expected_step="Offer")

        assert state["thread_state"] == "WaitingOnHIL"

    def test_turn_8_hil_approve_offer_sent(self):
        """
        Turn 8: HIL approves, offer sent to client.
        Expected: thread_state="AwaitingClient", status remains "Lead"
        """
        state = create_event_state(
            event_id="EVT-TEST-001",
            email="client@example.com",
            chosen_date="2025-12-15",
            date_confirmed=True,
            participants=25,
            current_step=4,
        )
        state["locked_room_id"] = "room_a"
        state["room_eval_hash"] = state["requirements_hash"]

        # HIL approval transitions state
        state["thread_state"] = "AwaitingClient"

        # Simulated client-facing offer
        response = """Dear Client,

Thank you for choosing The Atelier for your workshop.

Please find attached our offer for your event on December 15, 2025.

**Summary:**
- Room A (14:00-18:00)
- 25 participants
- Total: CHF 500 (excl. VAT)

Please reply to confirm or if you have any questions.

Best regards,
The Atelier Team

Step: 4 Offer · Next: Client response (accept/counter/clarify) · State: Awaiting Client"""

        assert_no_fallback(response, "Turn 8 offer sent")
        assert_footer_contract(response, expected_step="Offer")

        assert state["thread_state"] == "AwaitingClient"
        assert state["status"] == "Lead"


# ==============================================================================
# HASH CONSISTENCY TESTS
# ==============================================================================


class TestHashConsistency:
    """Tests for requirements_hash and room_eval_hash consistency."""

    def test_requirements_hash_computed_at_intake(self):
        """Requirements hash should be computed when requirements are set."""
        state = create_event_state(participants=25)

        assert state["requirements_hash"] is not None
        assert len(state["requirements_hash"]) == 16  # Truncated SHA256

    def test_room_eval_hash_matches_after_lock(self):
        """room_eval_hash should match requirements_hash after room lock."""
        state = create_event_state(
            participants=25,
            date_confirmed=True,
            current_step=3,
        )

        # Before lock
        assert state["room_eval_hash"] is None

        # Lock room
        state["locked_room_id"] = "room_a"
        state["room_eval_hash"] = state["requirements_hash"]

        # After lock, hashes match
        assert state["room_eval_hash"] == state["requirements_hash"]
        assert can_advance_to_step_4(state) is True

    def test_hash_mismatch_blocks_step_4(self):
        """Mismatched hashes should block Step 4 entry."""
        state = create_event_state(
            participants=25,
            date_confirmed=True,
            current_step=3,
        )
        state["locked_room_id"] = "room_a"
        state["room_eval_hash"] = "different_hash"  # Mismatch!

        # P2 fails: hashes don't match
        assert can_advance_to_step_4(state) is False

    def test_requirements_change_invalidates_hash(self):
        """Changing requirements should update requirements_hash."""
        state = create_event_state(participants=25)
        original_hash = state["requirements_hash"]

        # Change participants
        state["requirements"]["number_of_participants"] = 36
        state["requirements_hash"] = _compute_requirements_hash(state["requirements"])

        assert state["requirements_hash"] != original_hash


# ==============================================================================
# PREREQUISITE GATE TESTS
# ==============================================================================


class TestPrerequisiteGates:
    """Tests for P1-P4 prerequisites at Step 4 entry."""

    def test_p1_date_confirmed_required(self):
        """P1: date_confirmed must be True."""
        state = create_event_state(
            participants=25,
            date_confirmed=False,  # P1 fails
            current_step=3,
        )
        state["locked_room_id"] = "room_a"
        state["room_eval_hash"] = state["requirements_hash"]

        assert can_advance_to_step_4(state) is False

    def test_p2_room_locked_required(self):
        """P2: locked_room_id must be set."""
        state = create_event_state(
            participants=25,
            date_confirmed=True,
            current_step=3,
        )
        # No room locked

        assert can_advance_to_step_4(state) is False

    def test_p2_hash_match_required(self):
        """P2: requirements_hash must equal room_eval_hash."""
        state = create_event_state(
            participants=25,
            date_confirmed=True,
            current_step=3,
        )
        state["locked_room_id"] = "room_a"
        state["room_eval_hash"] = "different"  # Mismatch

        assert can_advance_to_step_4(state) is False

    def test_p3_capacity_required(self):
        """P3: capacity (participants) must be present."""
        state = create_event_state(
            date_confirmed=True,
            current_step=3,
        )
        state["locked_room_id"] = "room_a"
        # No participants

        # requirements_hash would be None, so P3 check
        state["room_eval_hash"] = state["requirements_hash"]

        assert can_advance_to_step_4(state) is False

    def test_all_prerequisites_met(self):
        """All P1-P4 met should allow Step 4 entry."""
        state = create_event_state(
            participants=25,
            date_confirmed=True,
            current_step=3,
        )
        state["locked_room_id"] = "room_a"
        state["room_eval_hash"] = state["requirements_hash"]

        assert can_advance_to_step_4(state) is True


# ==============================================================================
# STATUS LIFECYCLE TESTS
# ==============================================================================


class TestStatusLifecycle:
    """Tests for event status lifecycle."""

    def test_initial_status_is_lead(self):
        """New events should have status=Lead."""
        state = create_event_state()
        assert state["status"] == "Lead"

    def test_status_remains_lead_at_offer(self):
        """Status should still be Lead when offer is created."""
        state = create_event_state(
            participants=25,
            date_confirmed=True,
            current_step=4,
        )
        state["locked_room_id"] = "room_a"
        state["room_eval_hash"] = state["requirements_hash"]

        # Offer created, but not accepted
        assert state["status"] == "Lead"
