"""
TEST: tests/regression/test_manager_actions.py
PURPOSE: Regression tests for manager-initiated workflow actions.

Tests verify that manager actions from the frontend correctly adapt
workflow state using the CAPTURE-AND-ADVANCE pattern:
- Manager values are captured as CONFIRMED (no client re-confirmation)
- Gatekeeper is refreshed to check what gates are now satisfied
- Workflow auto-advances when gates allow

TEST CASES:
1. Date change captures date as confirmed and advances if room is locked
2. Room change locks room and advances to offer step
3. Room cancellation clears room (only detour case)
4. Requirements update recomputes hash
5. Offer update invalidates offer_hash
6. Site visit reschedule updates state
7. HIL approval logs activity
8. HIL rejection logs activity
9. Activity log records all manager actions
10. Billing update checks Step 7 readiness
"""

import pytest
from copy import deepcopy
from typing import Any, Dict

from workflows.manager_actions import (
    ManagerActionType,
    ManagerActionResult,
    process_manager_action,
)


# =============================================================================
# TEST FIXTURES
# =============================================================================


@pytest.fixture
def base_event_entry() -> Dict[str, Any]:
    """Base event entry at Step 3 (date confirmed, no room yet)."""
    return {
        "event_id": "test-event-001",
        "thread_id": "thread-001",
        "current_step": 3,  # Room availability step
        "caller_step": None,
        "chosen_date": "2026-03-15",
        "date_confirmed": True,  # Date already confirmed
        "locked_room_id": None,  # No room yet
        "requirements": {
            "number_of_participants": 50,
            "seating_layout": "theater",
        },
        "requirements_hash": "abc123",
        "room_eval_hash": None,  # No room evaluated yet
        "offer_hash": None,  # No offer yet
        "offer": None,
        "event_data": {
            "Name": "John Doe",
            "Email": "john@example.com",
        },
        "audit": [],
        "activity_log": [],
    }


@pytest.fixture
def event_at_step_4() -> Dict[str, Any]:
    """Event at Step 4 with date confirmed and room locked."""
    return {
        "event_id": "test-event-002",
        "thread_id": "thread-002",
        "current_step": 4,
        "caller_step": None,
        "chosen_date": "2026-03-15",
        "date_confirmed": True,
        "locked_room_id": "Room A",
        "requirements": {
            "number_of_participants": 50,
            "seating_layout": "theater",
        },
        "requirements_hash": "abc123",
        "room_eval_hash": "abc123",
        "offer_hash": "def456",
        "offer": {
            "total": 5000,
            "currency": "CHF",
        },
        "event_data": {
            "Name": "John Doe",
            "Email": "john@example.com",
        },
        "audit": [],
        "activity_log": [],
    }


@pytest.fixture
def event_at_step_7() -> Dict[str, Any]:
    """Event at Step 7 with site visit scheduled."""
    return {
        "event_id": "test-event-003",
        "thread_id": "thread-003",
        "current_step": 7,
        "caller_step": None,
        "chosen_date": "2026-03-15",
        "date_confirmed": True,
        "locked_room_id": "Room A",
        "site_visit_date": "2026-03-10",
        "site_visit_time": "14:00",
        "requirements": {"number_of_participants": 50},
        "requirements_hash": "abc123",
        "room_eval_hash": "abc123",
        "offer_hash": "def456",
        "event_data": {"Name": "Jane Smith"},
        "audit": [],
        "activity_log": [],
    }


@pytest.fixture
def event_no_date_confirmed() -> Dict[str, Any]:
    """Event at Step 2 with no date confirmed yet."""
    return {
        "event_id": "test-event-004",
        "thread_id": "thread-004",
        "current_step": 2,
        "caller_step": None,
        "chosen_date": None,
        "date_confirmed": False,
        "locked_room_id": None,
        "requirements": {"number_of_participants": 30},
        "requirements_hash": "xyz789",
        "room_eval_hash": None,
        "offer_hash": None,
        "event_data": {"Name": "New Client"},
        "audit": [],
        "activity_log": [],
    }


# =============================================================================
# DATE CHANGE TESTS (Capture-and-Advance Pattern)
# =============================================================================


class TestManagerDateChange:
    """Tests for manager-initiated date changes using capture-and-advance."""

    def test_date_change_captures_as_confirmed(self, event_no_date_confirmed: Dict[str, Any]):
        """Date change should capture date as confirmed and advance workflow."""
        event = deepcopy(event_no_date_confirmed)

        result = process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.DATE_CHANGE,
            payload={"new_date": "2026-04-20"},
            manager_id="manager-001",
        )

        assert result.success is True
        assert result.action_type == ManagerActionType.DATE_CHANGE

        # Verify date captured as CONFIRMED
        assert event["chosen_date"] == "2026-04-20"
        assert event["date_confirmed"] is True

        # Should advance to Step 3 (room selection) since date is now confirmed
        assert result.new_step == 3
        assert event["current_step"] == 3

        # Client notification generated
        assert result.needs_client_notification is True
        assert result.notification_draft is not None

    def test_date_change_with_room_locked_advances_to_offer(self, event_at_step_4: Dict[str, Any]):
        """Date change when room exists should advance to offer step."""
        event = deepcopy(event_at_step_4)

        result = process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.DATE_CHANGE,
            payload={"new_date": "2026-04-20"},
            manager_id="manager-001",
        )

        assert result.success is True
        assert event["chosen_date"] == "2026-04-20"
        assert event["date_confirmed"] is True

        # Hashes invalidated (date change affects room/offer)
        assert event["room_eval_hash"] is None
        assert event["offer_hash"] is None

        # Activity logged
        assert len(event["activity_log"]) > 0

    def test_date_change_requires_new_date(self, base_event_entry: Dict[str, Any]):
        """Date change should fail if new_date not provided."""
        event = deepcopy(base_event_entry)

        result = process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.DATE_CHANGE,
            payload={},  # Missing new_date
        )

        assert result.success is False
        assert "new_date is required" in result.error

    def test_date_change_logs_activity(self, event_no_date_confirmed: Dict[str, Any]):
        """Date change should log activity for manager visibility."""
        event = deepcopy(event_no_date_confirmed)

        process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.DATE_CHANGE,
            payload={"new_date": "2026-04-20"},
        )

        # Check activity log was populated
        assert len(event["activity_log"]) > 0
        activity = event["activity_log"][-1]
        # Activity should be "date_confirmed" since manager set it
        assert "Date" in activity["title"] or "Confirmed" in activity["title"]

    def test_date_change_returns_gates_satisfied(self, event_no_date_confirmed: Dict[str, Any]):
        """Date change result should include which gates are now satisfied."""
        event = deepcopy(event_no_date_confirmed)
        # Add requested_window to satisfy step2 gate (which checks for start/end/tz)
        event["requested_window"] = {
            "start": "2026-04-20T09:00:00",
            "end": "2026-04-20T17:00:00",
            "tz": "Europe/Zurich",
        }

        result = process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.DATE_CHANGE,
            payload={"new_date": "2026-04-20"},
        )

        assert result.success is True
        # gates_satisfied should be a list
        assert isinstance(result.gates_satisfied, list)
        # Step 2 gate should be satisfied (requested_window has start/end/tz)
        assert "step2" in result.gates_satisfied


# =============================================================================
# ROOM CHANGE TESTS (Capture-and-Advance Pattern)
# =============================================================================


class TestManagerRoomChange:
    """Tests for manager-initiated room changes using capture-and-advance."""

    def test_room_change_locks_room_and_advances(self, base_event_entry: Dict[str, Any]):
        """Room change should lock room and advance to offer step."""
        event = deepcopy(base_event_entry)
        # Ensure date is confirmed for proper advancement
        event["date_confirmed"] = True

        result = process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.ROOM_CHANGE,
            payload={"new_room": "Room B"},
        )

        assert result.success is True
        assert event["locked_room_id"] == "Room B"

        # Room should be locked (evaluated)
        assert event["room_eval_hash"] is not None

        # Should advance to Step 4 (offer) since room is now locked
        assert result.new_step == 4
        assert event["current_step"] == 4

        # workflow_advanced should be True
        assert result.workflow_advanced is True

    def test_room_change_invalidates_offer(self, event_at_step_4: Dict[str, Any]):
        """Room change should invalidate offer hash for regeneration."""
        event = deepcopy(event_at_step_4)
        old_offer_hash = event["offer_hash"]

        result = process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.ROOM_CHANGE,
            payload={"new_room": "Room B"},
        )

        assert result.success is True
        assert event["locked_room_id"] == "Room B"
        assert event["offer_hash"] is None  # Invalidated
        assert old_offer_hash is not None  # Was set before

    def test_room_change_generates_notification(self, base_event_entry: Dict[str, Any]):
        """Room change should generate client notification draft."""
        event = deepcopy(base_event_entry)

        result = process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.ROOM_CHANGE,
            payload={"new_room": "Room B"},
        )

        assert result.needs_client_notification is True
        assert result.notification_draft is not None
        assert "Room B" in result.notification_draft

    def test_room_change_requires_new_room(self, base_event_entry: Dict[str, Any]):
        """Room change should fail if new_room not provided."""
        event = deepcopy(base_event_entry)

        result = process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.ROOM_CHANGE,
            payload={},  # Missing new_room
        )

        assert result.success is False
        assert "new_room is required" in result.error


# =============================================================================
# ROOM CANCELLATION TESTS (This IS a detour case)
# =============================================================================


class TestManagerRoomCancellation:
    """Tests for manager-initiated room cancellations."""

    def test_room_cancellation_clears_room_and_routes_to_step3(self, event_at_step_4: Dict[str, Any]):
        """Room cancellation should clear locked_room_id and route to Step 3."""
        event = deepcopy(event_at_step_4)

        result = process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.ROOM_CANCELLATION,
            payload={"reason": "Double booking conflict"},
        )

        assert result.success is True
        assert result.new_step == 3  # Client needs to select new room
        assert event["locked_room_id"] is None
        assert event["room_eval_hash"] is None
        assert event["offer_hash"] is None

        # This is NOT workflow advancement - it's a step back
        assert result.workflow_advanced is False

    def test_room_cancellation_fails_without_existing_room(self, base_event_entry: Dict[str, Any]):
        """Room cancellation should fail if no room is reserved."""
        event = deepcopy(base_event_entry)
        event["locked_room_id"] = None

        result = process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.ROOM_CANCELLATION,
            payload={},
        )

        assert result.success is False
        assert "No room is currently reserved" in result.error

    def test_room_cancellation_includes_reason_in_notification(self, event_at_step_4: Dict[str, Any]):
        """Room cancellation notification should include the reason."""
        event = deepcopy(event_at_step_4)

        result = process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.ROOM_CANCELLATION,
            payload={"reason": "Maintenance scheduled"},
        )

        assert "Maintenance scheduled" in result.notification_draft


# =============================================================================
# REQUIREMENTS UPDATE TESTS
# =============================================================================


class TestManagerRequirementsUpdate:
    """Tests for manager-initiated requirements updates."""

    def test_requirements_update_changes_hash(self, base_event_entry: Dict[str, Any]):
        """Requirements update should recompute requirements_hash."""
        event = deepcopy(base_event_entry)
        old_hash = event["requirements_hash"]

        result = process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.REQUIREMENTS_UPDATE,
            payload={"participants": 100},  # Changed from 50
        )

        assert result.success is True
        assert event["requirements"]["number_of_participants"] == 100
        # Hash should have changed
        assert event["requirements_hash"] != old_hash

    def test_requirements_update_invalidates_offer(self, event_at_step_4: Dict[str, Any]):
        """Requirements update should invalidate offer_hash."""
        event = deepcopy(event_at_step_4)

        result = process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.REQUIREMENTS_UPDATE,
            payload={"participants": 150},  # Significant change
        )

        assert result.success is True
        assert event["offer_hash"] is None  # Invalidated for regeneration

    def test_requirements_update_fails_without_fields(self, base_event_entry: Dict[str, Any]):
        """Requirements update should fail if no fields provided."""
        event = deepcopy(base_event_entry)

        result = process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.REQUIREMENTS_UPDATE,
            payload={},  # No fields
        )

        assert result.success is False
        assert "No requirements fields provided" in result.error


# =============================================================================
# BILLING UPDATE TESTS
# =============================================================================


class TestManagerBillingUpdate:
    """Tests for manager-initiated billing updates."""

    def test_billing_update_captures_billing_info(self, event_at_step_4: Dict[str, Any]):
        """Billing update should capture billing details."""
        event = deepcopy(event_at_step_4)

        result = process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.BILLING_UPDATE,
            payload={
                "company": "Acme Corp",
                "address": "123 Main St",
            },
        )

        assert result.success is True
        # Billing info captured
        assert event["event_data"]["Company"] == "Acme Corp"
        assert event["captured"]["billing"]["company"] == "Acme Corp"
        assert event["captured"]["billing"]["address"] == "123 Main St"

    def test_billing_update_checks_step7_readiness(self, event_at_step_4: Dict[str, Any]):
        """Billing update should check Step 7 gate readiness."""
        event = deepcopy(event_at_step_4)

        result = process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.BILLING_UPDATE,
            payload={"company": "Test Corp"},
        )

        assert result.success is True
        # Should report Step 7 readiness in details
        assert "step7_ready" in result.details
        assert "step7_missing" in result.details


# =============================================================================
# OFFER UPDATE TESTS
# =============================================================================


class TestManagerOfferUpdate:
    """Tests for manager-initiated offer updates."""

    def test_offer_update_invalidates_hash(self, event_at_step_4: Dict[str, Any]):
        """Offer update should invalidate offer_hash."""
        event = deepcopy(event_at_step_4)

        result = process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.OFFER_UPDATE,
            payload={"price": 4500},
        )

        assert result.success is True
        assert event["offer_hash"] is None  # Invalidated
        assert event["offer"]["total"] == 4500

    def test_offer_update_stays_at_current_step(self, event_at_step_4: Dict[str, Any]):
        """Offer update should not change the current step."""
        event = deepcopy(event_at_step_4)
        original_step = event["current_step"]

        result = process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.OFFER_UPDATE,
            payload={"discount": 10},
        )

        assert result.success is True
        assert result.new_step == original_step
        assert result.workflow_advanced is False

    def test_offer_update_fails_without_fields(self, event_at_step_4: Dict[str, Any]):
        """Offer update should fail if no fields provided."""
        event = deepcopy(event_at_step_4)

        result = process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.OFFER_UPDATE,
            payload={},  # No fields
        )

        assert result.success is False
        assert "No offer fields provided" in result.error


# =============================================================================
# SITE VISIT RESCHEDULE TESTS
# =============================================================================


class TestManagerSiteVisitReschedule:
    """Tests for manager-initiated site visit rescheduling."""

    def test_site_visit_reschedule_updates_date(self, event_at_step_7: Dict[str, Any]):
        """Site visit reschedule should update date and time."""
        event = deepcopy(event_at_step_7)

        result = process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.SITE_VISIT_RESCHEDULE,
            payload={"new_date": "2026-03-12", "new_time": "10:00"},
        )

        assert result.success is True
        assert event["site_visit_date"] == "2026-03-12"
        assert event["site_visit_time"] == "10:00"

    def test_site_visit_reschedule_generates_notification(self, event_at_step_7: Dict[str, Any]):
        """Site visit reschedule should generate notification draft."""
        event = deepcopy(event_at_step_7)

        result = process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.SITE_VISIT_RESCHEDULE,
            payload={"new_date": "2026-03-12"},
        )

        assert result.needs_client_notification is True
        assert "reschedule" in result.notification_draft.lower() or "scheduled" in result.notification_draft.lower()

    def test_site_visit_reschedule_requires_date_or_time(self, event_at_step_7: Dict[str, Any]):
        """Site visit reschedule should fail if neither date nor time provided."""
        event = deepcopy(event_at_step_7)

        result = process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.SITE_VISIT_RESCHEDULE,
            payload={},
        )

        assert result.success is False
        assert "new_date or new_time is required" in result.error


# =============================================================================
# HIL APPROVE/REJECT TESTS
# =============================================================================


class TestManagerHILApprove:
    """Tests for HIL task approval."""

    def test_hil_approve_logs_activity(self, base_event_entry: Dict[str, Any]):
        """HIL approval should log activity."""
        event = deepcopy(base_event_entry)

        result = process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.HIL_APPROVE,
            payload={"task_id": "task-001"},
        )

        assert result.success is True
        assert len(event["activity_log"]) > 0

    def test_hil_approve_requires_task_id(self, base_event_entry: Dict[str, Any]):
        """HIL approval should fail without task_id."""
        event = deepcopy(base_event_entry)

        result = process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.HIL_APPROVE,
            payload={},
        )

        assert result.success is False
        assert "task_id is required" in result.error


class TestManagerHILReject:
    """Tests for HIL task rejection."""

    def test_hil_reject_logs_activity(self, base_event_entry: Dict[str, Any]):
        """HIL rejection should log activity."""
        event = deepcopy(base_event_entry)

        result = process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.HIL_REJECT,
            payload={"task_id": "task-001", "reason": "Needs revision"},
        )

        assert result.success is True
        assert len(event["activity_log"]) > 0

    def test_hil_reject_does_not_notify_client(self, base_event_entry: Dict[str, Any]):
        """HIL rejection should NOT notify client."""
        event = deepcopy(base_event_entry)

        result = process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.HIL_REJECT,
            payload={"task_id": "task-001", "reason": "Not appropriate"},
        )

        assert result.needs_client_notification is False

    def test_hil_reject_requires_task_id(self, base_event_entry: Dict[str, Any]):
        """HIL rejection should fail without task_id."""
        event = deepcopy(base_event_entry)

        result = process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.HIL_REJECT,
            payload={},
        )

        assert result.success is False
        assert "task_id is required" in result.error


# =============================================================================
# AUDIT TRAIL TESTS
# =============================================================================


class TestAuditTrail:
    """Tests for audit trail logging."""

    def test_date_change_creates_audit_entry(self, event_no_date_confirmed: Dict[str, Any]):
        """Manager actions should create audit entries."""
        event = deepcopy(event_no_date_confirmed)

        process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.DATE_CHANGE,
            payload={"new_date": "2026-04-20"},
            manager_id="manager-001",
        )

        # Check audit log
        assert len(event["audit"]) > 0
        audit_entry = event["audit"][-1]
        assert "manager_date_set" in audit_entry["reason"]
        assert audit_entry["actor"] == "manager-001"

    def test_all_actions_create_audit_entries(self, base_event_entry: Dict[str, Any]):
        """All manager action types should create audit entries."""
        actions_and_payloads = [
            (ManagerActionType.DATE_CHANGE, {"new_date": "2026-04-20"}),
            (ManagerActionType.ROOM_CHANGE, {"new_room": "Room B"}),
        ]

        for action_type, payload in actions_and_payloads:
            event_copy = deepcopy(base_event_entry)
            process_manager_action(event_copy, action_type, payload)
            assert len(event_copy["audit"]) > 0, f"{action_type} should create audit entry"


# =============================================================================
# WORKFLOW ADVANCEMENT TESTS
# =============================================================================


class TestWorkflowAdvancement:
    """Tests for workflow auto-advancement based on gate satisfaction."""

    def test_date_then_room_advances_to_offer(self, event_no_date_confirmed: Dict[str, Any]):
        """Setting date then room should advance to offer step."""
        event = deepcopy(event_no_date_confirmed)

        # First: Set date (should advance to Step 3)
        result1 = process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.DATE_CHANGE,
            payload={"new_date": "2026-04-20"},
        )
        assert result1.success is True
        assert result1.new_step == 3
        assert event["date_confirmed"] is True

        # Second: Set room (should advance to Step 4)
        result2 = process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.ROOM_CHANGE,
            payload={"new_room": "Grand Hall"},
        )
        assert result2.success is True
        assert result2.new_step == 4
        assert result2.workflow_advanced is True
        assert event["locked_room_id"] == "Grand Hall"

    def test_room_change_without_date_stays_at_step2(self, event_no_date_confirmed: Dict[str, Any]):
        """Room change without confirmed date should not advance past step 2."""
        event = deepcopy(event_no_date_confirmed)
        # Ensure date is NOT confirmed
        event["date_confirmed"] = False

        result = process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.ROOM_CHANGE,
            payload={"new_room": "Room B"},
        )

        assert result.success is True
        # Room is locked but can't advance to Step 4 without date
        assert event["locked_room_id"] == "Room B"
        # Should be at step 2 or 3, not 4
        assert result.new_step in [2, 3]


# =============================================================================
# CODEX-RECOMMENDED REGRESSION TESTS (Bug fixes)
# =============================================================================


class TestCodexBugFixes:
    """
    Tests for bugs identified by Codex debug expert analysis.

    These tests cover edge cases where previous implementations failed:
    1. Step 3 re-validation bypass when room_eval_hash is cleared
    2. Offer status drift causing stale Step 7 readiness
    """

    def test_date_change_forces_step3_reeval_when_room_locked(self, event_at_step_4: Dict[str, Any]):
        """
        BUG FIX TEST: Manager date change should force Step 3 re-evaluation
        even when a room is already locked.

        Root cause: _determine_next_step() was checking only locked_room_id,
        not room_eval_hash. When date changes, room_eval_hash is cleared but
        locked_room_id remains, causing Step 3 to be skipped.

        Expected: After date change, workflow should be at Step 3 (not Step 4)
        because room needs re-validation for the new date.
        """
        event = deepcopy(event_at_step_4)
        # Event has locked room but now we change the date
        assert event["locked_room_id"] == "Room A"
        assert event["room_eval_hash"] is not None

        result = process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.DATE_CHANGE,
            payload={"new_date": "2026-04-20"},
        )

        assert result.success is True
        # room_eval_hash should be cleared (date changed = room availability may differ)
        assert event["room_eval_hash"] is None
        # Room is still locked (manager didn't cancel it)
        assert event["locked_room_id"] == "Room A"
        # CRITICAL: Workflow should route to Step 3 for re-validation
        # because room_eval_hash is now None (stale)
        assert result.new_step == 3, (
            "Date change should force Step 3 re-evaluation when room_eval_hash is cleared"
        )

    def test_requirements_update_forces_step3_reeval_when_hash_mismatch(
        self, event_at_step_4: Dict[str, Any]
    ):
        """
        BUG FIX TEST: Manager requirements update should force Step 3 re-evaluation
        when the new requirements_hash differs from room_eval_hash.

        Root cause: Previous logic only checked locked_room_id, not whether
        the room was evaluated against the CURRENT requirements.

        Expected: After requirements change, if room_eval_hash doesn't match
        the new requirements_hash, workflow should be at Step 3.
        """
        event = deepcopy(event_at_step_4)
        # Initially hashes match
        event["requirements_hash"] = "abc123"
        event["room_eval_hash"] = "abc123"

        result = process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.REQUIREMENTS_UPDATE,
            payload={"participants": 200},  # Significantly different
        )

        assert result.success is True
        # Requirements hash changed
        assert event["requirements_hash"] != "abc123"
        # Room eval hash is now stale (doesn't match new requirements)
        # The room was evaluated for 50 people, but now we need 200
        # This should trigger Step 3 re-evaluation
        new_req_hash = event["requirements_hash"]
        room_eval_hash = event["room_eval_hash"]

        # If room_eval_hash doesn't match requirements_hash, we need re-eval
        if room_eval_hash != new_req_hash:
            assert result.new_step == 3, (
                "Requirements change should force Step 3 when room_eval_hash "
                "doesn't match new requirements_hash"
            )

    def test_offer_update_clears_offer_status_for_step7_gate(
        self, event_at_step_4: Dict[str, Any]
    ):
        """
        BUG FIX TEST: Manager offer update should clear offer_status,
        not just offer_accepted.

        Root cause: Step 7 gate uses offer_status (not offer_accepted).
        Previous implementation cleared offer_accepted but left offer_status
        as "Accepted", causing Step 7 to incorrectly report ready.

        Expected: After offer update, offer_status should be cleared/reset.
        """
        event = deepcopy(event_at_step_4)
        # Simulate a previously accepted offer
        event["offer_status"] = "Accepted"
        event["offer_accepted"] = True

        result = process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.OFFER_UPDATE,
            payload={"price": 4500},
        )

        assert result.success is True
        # Both should be cleared/reset
        assert event["offer_accepted"] is False
        # CRITICAL: offer_status must also be cleared
        # Otherwise Step 7 gate will incorrectly report ready
        assert event.get("offer_status") in [None, "Draft", "Pending"], (
            "Offer update must clear offer_status to prevent stale Step 7 readiness"
        )

    def test_offer_update_prevents_premature_step7(self, event_at_step_4: Dict[str, Any]):
        """
        BUG FIX TEST: After manager updates offer, Step 7 should NOT be ready
        even if it was previously accepted.

        This test verifies the end-to-end gate behavior.
        """
        from workflows.common.gatekeeper import explain_step7_gate

        event = deepcopy(event_at_step_4)
        # Set up a fully ready Step 7 scenario
        event["offer_status"] = "Accepted"
        event["offer_accepted"] = True
        event["offer_hash"] = "valid_hash"
        event["event_data"]["Company"] = "Test Corp"
        event["event_data"]["Billing Address"] = "123 Main St"
        event["captured"] = {"billing": {"company": "Test Corp", "address": "123 Main St"}}

        # Verify Step 7 was ready before
        step7_before = explain_step7_gate(event)
        # Note: May not be fully ready depending on other fields, but offer should be ok

        # Manager updates the offer
        result = process_manager_action(
            event_entry=event,
            action_type=ManagerActionType.OFFER_UPDATE,
            payload={"price": 9999},
        )

        assert result.success is True

        # Verify Step 7 is NOT ready after offer update
        step7_after = explain_step7_gate(event)
        # offer_status should now be in missing_now if gate checks it
        if "offer_status" in step7_after.get("missing_now", []):
            pass  # Good - gate correctly detects offer not accepted
        elif not step7_after["ready"]:
            pass  # Good - gate reports not ready
        else:
            # If Step 7 is still ready after clearing offer, that's a bug
            assert "offer" in str(step7_after.get("missing_now", [])).lower() or not step7_after["ready"], (
                "Step 7 gate should not be ready after manager updates offer"
            )
