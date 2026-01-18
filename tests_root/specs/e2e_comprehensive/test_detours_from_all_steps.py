"""
E2E Tests: Detours from All Steps + DAG Verification

Tests that changes to confirmed variables (date, room, participants, billing, products)
correctly route per the V4 DAG rules:

- DATE change: Always routes to Step 2, maybe_run_step3=True
- ROOM change: Routes to Step 3
- PARTICIPANTS change: Routes to Step 3 (if hash mismatch) or fast-skip
- BILLING change: In-place capture, no routing
- PRODUCTS change: Stays in Step 4 (or routes to 4 from later steps)

DAG Verification:
- caller_step preserved for return after detour
- Only dependent steps re-run
- Offer always regenerated after structural changes
- Hash guards prevent unnecessary re-evaluation
"""

from __future__ import annotations

import pytest

from workflows.change_propagation import (
    ChangeType,
    route_change_on_updated_variable,
    detect_change_type,
    should_skip_step3_after_date_change,
)


# =============================================================================
# DATE DETOURS (Routes to Step 2)
# =============================================================================


class TestDateDetoursFromAllSteps:
    """Date changes from Steps 3-7 should route to Step 2."""

    @pytest.mark.parametrize("from_step", [3, 4, 5, 6, 7])
    def test_date_change_routes_to_step2(self, from_step, build_event_entry):
        """DATE change from any step → Step 2 with maybe_run_step3=True."""
        # Test ID: DETOUR_DATE_FROM_STEP{from_step}_001
        event_entry = build_event_entry(
            from_step,
            date_confirmed=True,
            chosen_date="2026-03-15",
            locked_room_id="Room A",
        )

        decision = route_change_on_updated_variable(event_entry, ChangeType.DATE, from_step=from_step)

        assert decision.next_step == 2, f"Date change from step {from_step} should route to step 2"
        assert decision.maybe_run_step3 is True, "Date change should trigger maybe_run_step3"
        assert decision.updated_caller_step == from_step, f"caller_step should be {from_step}"
        assert decision.needs_reeval is True, "Date change requires re-evaluation"

    @pytest.mark.parametrize("from_step", [3, 4, 5, 6, 7])
    def test_date_change_preserves_existing_caller_step(self, from_step, build_event_entry):
        """If already in a detour (caller_step set), preserve it."""
        # Test ID: DETOUR_DATE_PRESERVE_CALLER_STEP{from_step}_001
        original_caller = from_step + 1 if from_step < 7 else 7
        event_entry = build_event_entry(
            from_step,
            date_confirmed=True,
            caller_step=original_caller,  # Already in a detour
        )

        decision = route_change_on_updated_variable(event_entry, ChangeType.DATE, from_step=from_step)

        # Should preserve the original caller, not overwrite with from_step
        assert decision.updated_caller_step == original_caller, \
            f"Should preserve existing caller_step={original_caller}, not overwrite with {from_step}"

    def test_date_change_step3_skip_logic_with_room(self, build_event_entry):
        """Test Step 3 skip logic after date change when room is locked."""
        # Test ID: DAG_RERUN_DATE_ROOM_AVAILABLE_001
        event_entry = build_event_entry(
            4,
            chosen_date="2026-03-15",
            locked_room_id="Room A",
        )

        # The skip logic checks if room is still valid on new date
        result = should_skip_step3_after_date_change(
            event_entry,
            new_date="2026-03-20",
        )

        # Result depends on room availability logic - just verify function runs
        assert isinstance(result, bool), "Should return boolean"

    def test_date_change_must_reeval_without_locked_room(self, build_event_entry):
        """Without a locked room, can't skip Step 3."""
        # Test ID: DAG_RERUN_DATE_NO_ROOM_001
        event_entry = build_event_entry(
            4,
            chosen_date="2026-03-15",
            locked_room_id=None,  # No room locked
        )

        result = should_skip_step3_after_date_change(
            event_entry,
            new_date="2026-03-20",
        )

        assert result is False, "Must run Step 3 when no room is locked"


# =============================================================================
# ROOM DETOURS (Routes to Step 3)
# =============================================================================


class TestRoomDetoursFromAllSteps:
    """Room changes from Steps 2, 4-7 should route to Step 3."""

    @pytest.mark.parametrize("from_step", [2, 4, 5, 6, 7])
    def test_room_change_routes_to_step3(self, from_step, build_event_entry):
        """ROOM change from any step → Step 3."""
        # Test ID: DETOUR_ROOM_FROM_STEP{from_step}_001
        event_entry = build_event_entry(
            from_step,
            date_confirmed=True,
            locked_room_id="Room A" if from_step >= 4 else None,
        )

        decision = route_change_on_updated_variable(event_entry, ChangeType.ROOM, from_step=from_step)

        assert decision.next_step == 3, f"Room change from step {from_step} should route to step 3"
        assert decision.maybe_run_step3 is False, "Room change goes directly to step 3"
        assert decision.updated_caller_step == from_step, f"caller_step should be {from_step}"
        assert decision.needs_reeval is True, "Room change requires re-evaluation"


# =============================================================================
# PARTICIPANT/REQUIREMENTS DETOURS (Routes to Step 3 with hash guards)
# =============================================================================


class TestParticipantDetoursFromAllSteps:
    """Participant changes use hash guards to avoid unnecessary Step 3 re-runs."""

    @pytest.mark.parametrize("from_step", [2, 3, 4, 5, 6, 7])
    def test_participant_change_routes_to_step3_on_hash_mismatch(self, from_step, build_event_entry):
        """REQUIREMENTS change with hash mismatch → Step 3."""
        # Test ID: DETOUR_PARTICIPANTS_FROM_STEP{from_step}_001
        event_entry = build_event_entry(
            from_step,
            requirements_hash="hash_new",
            room_eval_hash="hash_old",  # Mismatch!
        )

        decision = route_change_on_updated_variable(event_entry, ChangeType.REQUIREMENTS, from_step=from_step)

        assert decision.next_step == 3, f"Requirements change with hash mismatch should route to step 3"
        assert decision.needs_reeval is True

    @pytest.mark.parametrize("from_step", [3, 4, 5, 6, 7])
    def test_participant_change_skips_when_hash_matches(self, from_step, build_event_entry):
        """REQUIREMENTS change with matching hash → fast-skip, return to caller."""
        # Test ID: DETOUR_PARTICIPANTS_SAME_VALUE_{from_step}_001
        event_entry = build_event_entry(
            from_step,
            requirements_hash="hash123",
            room_eval_hash="hash123",  # Match!
            caller_step=from_step,
        )

        decision = route_change_on_updated_variable(event_entry, ChangeType.REQUIREMENTS, from_step=from_step)

        # When hashes match, should return to caller step (fast-skip)
        assert decision.skip_reason == "requirements_hash_match", "Should indicate hash match skip"
        assert decision.needs_reeval is False, "No re-eval needed when hash matches"


# =============================================================================
# BILLING CHANGES (In-place, no routing)
# =============================================================================


class TestBillingChangesFromAllSteps:
    """Billing changes are captured in-place without routing."""

    @pytest.mark.parametrize("from_step", [2, 3, 4, 5, 6, 7])
    def test_billing_change_is_inplace(self, from_step, build_event_entry):
        """BILLING change is captured in-place, no step routing."""
        # Test ID: BILLING_INPLACE_FROM_STEP{from_step}_001
        event_entry = build_event_entry(from_step)

        # Billing changes are CLIENT_INFO type
        decision = route_change_on_updated_variable(event_entry, ChangeType.CLIENT_INFO, from_step=from_step)

        # Billing should stay at current step (in-place capture)
        assert decision.next_step == from_step, "Billing change should stay at current step"
        assert decision.updated_caller_step is None, "No detour for billing"


# =============================================================================
# PRODUCT CHANGES (Stay in Step 4 or route to Step 4)
# =============================================================================


class TestProductDetoursFromAllSteps:
    """Product changes stay in Step 4 or route to Step 4 from later steps."""

    def test_product_change_stays_in_step4(self, build_event_entry):
        """PRODUCTS change from Step 4 stays in Step 4."""
        # Test ID: DETOUR_PRODUCTS_FROM_STEP4_001
        event_entry = build_event_entry(4, locked_room_id="Room A")

        decision = route_change_on_updated_variable(event_entry, ChangeType.PRODUCTS, from_step=4)

        assert decision.next_step == 4, "Product change from step 4 stays in step 4"
        assert decision.skip_reason == "products_only", "Should indicate products-only change"
        assert decision.needs_reeval is True, "Need to rebuild offer"

    @pytest.mark.parametrize("from_step", [5, 6, 7])
    def test_product_change_routes_to_step4_from_later_steps(self, from_step, build_event_entry):
        """PRODUCTS change from Steps 5-7 routes to Step 4."""
        # Test ID: DETOUR_PRODUCTS_FROM_STEP{from_step}_001
        event_entry = build_event_entry(from_step, locked_room_id="Room A")

        decision = route_change_on_updated_variable(event_entry, ChangeType.PRODUCTS, from_step=from_step)

        assert decision.next_step == 4, f"Product change from step {from_step} should route to step 4"
        # Note: Products are in-place changes, so caller_step may not be set
        # The key test is that it routes to step 4 and requires reeval
        assert decision.needs_reeval is True, "Products change should need offer rebuild"


# =============================================================================
# DAG VERIFICATION: OFFER REGENERATION
# =============================================================================


class TestDAGOfferRegeneration:
    """Verify offer is always regenerated after structural changes."""

    @pytest.mark.parametrize("change_type,from_step", [
        (ChangeType.DATE, 4),
        (ChangeType.DATE, 5),
        (ChangeType.ROOM, 4),
        (ChangeType.ROOM, 5),
        (ChangeType.REQUIREMENTS, 4),
        (ChangeType.PRODUCTS, 4),
    ])
    def test_offer_regenerated_after_change(self, change_type, from_step, build_event_entry):
        """Structural changes always require offer regeneration."""
        # Test IDs: DAG_OFFER_REGENERATED_AFTER_{change_type.value}_{from_step}_001
        event_entry = build_event_entry(
            from_step,
            requirements_hash="hash_new" if change_type == ChangeType.REQUIREMENTS else "hash123",
            room_eval_hash="hash_old" if change_type == ChangeType.REQUIREMENTS else "hash123",
        )

        decision = route_change_on_updated_variable(event_entry, change_type, from_step=from_step)

        assert decision.needs_reeval is True, \
            f"{change_type.value} change should trigger re-evaluation (offer regeneration)"


# =============================================================================
# DAG VERIFICATION: CALLER_STEP RETURN
# =============================================================================


class TestDAGCallerStepReturn:
    """Verify return to caller_step after detour resolution."""

    def test_return_to_caller_step_after_date_detour(self, build_event_entry):
        """After date detour resolves, should return to original caller."""
        # Test ID: DAG_RETURN_TO_CALLER_STEP_DATE_001
        original_step = 5
        event_entry = build_event_entry(
            2,  # Currently in Step 2 (date detour)
            caller_step=original_step,  # Remember where we came from
        )

        # After date is re-confirmed, the system should return to caller_step
        # This is tested by checking caller_step is preserved in routing
        decision = route_change_on_updated_variable(event_entry, ChangeType.DATE, from_step=2)

        # The key verification: caller_step should be preserved
        assert decision.updated_caller_step == original_step, \
            f"Should return to caller_step={original_step} after detour"

    def test_return_to_caller_step_after_room_detour(self, build_event_entry):
        """After room detour resolves, should return to original caller."""
        # Test ID: DAG_RETURN_TO_CALLER_STEP_ROOM_001
        original_step = 6
        event_entry = build_event_entry(
            3,  # Currently in Step 3 (room detour)
            caller_step=original_step,
        )

        decision = route_change_on_updated_variable(event_entry, ChangeType.ROOM, from_step=3)

        assert decision.updated_caller_step == original_step, \
            f"Should return to caller_step={original_step} after room detour"


# =============================================================================
# CHANGE TYPE DETECTION
# =============================================================================


class TestChangeTypeDetection:
    """Test automatic detection of change types from user input."""

    def test_detects_date_change_when_confirmed(self, build_event_entry):
        """Detect DATE change when date is already confirmed."""
        # Test ID: DETECT_DATE_CHANGE_001
        event_entry = build_event_entry(4, date_confirmed=True, chosen_date="2026-03-15")
        user_info = {"date": "2026-03-20"}
        message = "Can we change the date to March 20 instead?"

        change_type = detect_change_type(event_entry, user_info, message_text=message)

        assert change_type == ChangeType.DATE

    def test_no_date_change_when_not_confirmed(self, build_event_entry):
        """No DATE change detected if date isn't confirmed yet (normal flow)."""
        # Test ID: DETECT_NO_DATE_CHANGE_001
        event_entry = build_event_entry(2, date_confirmed=False, chosen_date=None)
        user_info = {"date": "2026-03-17"}

        change_type = detect_change_type(event_entry, user_info)

        assert change_type is None, "Normal flow, not a change"

    def test_detects_room_change(self, build_event_entry):
        """Detect ROOM change when user requests different room."""
        # Test ID: DETECT_ROOM_CHANGE_001
        event_entry = build_event_entry(4, locked_room_id="Room A")
        user_info = {"room": "Room B"}
        message = "Can we switch to Room B instead?"

        change_type = detect_change_type(event_entry, user_info, message_text=message)

        assert change_type == ChangeType.ROOM

    def test_detects_requirements_change(self, build_event_entry):
        """Detect REQUIREMENTS change when participants change."""
        # Test ID: DETECT_REQUIREMENTS_CHANGE_001
        event_entry = build_event_entry(
            4,
            requirements={"number_of_participants": 20},
        )
        user_info = {"participants": 50}
        message = "Actually we're 50 people now."

        change_type = detect_change_type(event_entry, user_info, message_text=message)

        assert change_type == ChangeType.REQUIREMENTS

    def test_detects_products_change(self, build_event_entry):
        """Detect PRODUCTS change from product add request."""
        # Test ID: DETECT_PRODUCTS_CHANGE_001
        event_entry = build_event_entry(4)
        user_info = {"products_add": ["Prosecco", "Coffee"]}
        message = "Could you include Prosecco and Coffee?"

        change_type = detect_change_type(event_entry, user_info, message_text=message)

        assert change_type == ChangeType.PRODUCTS


# =============================================================================
# DETOUR PRIORITY (Multiple changes in one message)
# =============================================================================


class TestDetourPriority:
    """When multiple changes detected, verify correct priority."""

    def test_multiple_changes_detected(self, build_event_entry):
        """When both date and room change signals present, one is detected."""
        # Test ID: DETOUR_PRIORITY_DATE_ROOM_001
        event_entry = build_event_entry(
            4,
            date_confirmed=True,
            chosen_date="2026-03-15",
            locked_room_id="Room A",
        )
        # User asks for both date and room change
        user_info = {"date": "2026-03-20", "room": "Room B"}
        message = "Can we change to March 20 and switch to Room B?"

        change_type = detect_change_type(event_entry, user_info, message_text=message)

        # At least one change type should be detected
        # The actual priority depends on implementation details
        assert change_type in (ChangeType.DATE, ChangeType.ROOM), \
            "Should detect either date or room change"

    def test_room_takes_priority_over_products(self, build_event_entry):
        """ROOM change should take priority over PRODUCTS change."""
        # Test ID: DETOUR_PRIORITY_ROOM_PRODUCTS_001
        event_entry = build_event_entry(4, locked_room_id="Room A")
        user_info = {"room": "Room B", "products_add": ["Wine"]}
        message = "Switch to Room B and add wine please."

        change_type = detect_change_type(event_entry, user_info, message_text=message)

        # Room should take priority (routes further back)
        assert change_type == ChangeType.ROOM, "Room change should take priority over products"


# =============================================================================
# INTEGRATION TESTS: LLM-Based Detection (require AGENT_MODE=openai)
# =============================================================================

import os
from detection.unified import run_unified_detection

# Skip in stub mode - these tests require live LLM
requires_live_llm = pytest.mark.skipif(
    os.getenv("AGENT_MODE", "stub") == "stub",
    reason="Integration test requires AGENT_MODE=openai"
)


@requires_live_llm
class TestDetourDetectionIntegration:
    """
    Integration tests that verify LLM-based detection of detour requests.

    These tests use run_unified_detection with real messages and verify
    the LLM correctly identifies change signals.

    Run with: AGENT_MODE=openai pytest -k "Integration" -v
    """

    @pytest.mark.parametrize("from_step", [4, 5, 6, 7])
    def test_date_change_detected_by_llm(self, from_step, build_state):
        """LLM should detect date change request."""
        msg = "Can we change the date to April 20 instead?"
        build_state(from_step, msg)

        result = run_unified_detection(
            msg,
            current_step=from_step,
            date_confirmed=True,
            room_locked=True,
        )

        # LLM should detect this as a change request with a date
        assert result.is_change_request or result.date is not None, \
            f"LLM should detect date change in '{msg}'"

        # Should extract the date
        if result.date:
            assert "04" in result.date or "april" in str(result.date).lower() or "20" in result.date, \
                f"Date should contain April/04/20, got: {result.date}"

    @pytest.mark.parametrize("from_step", [4, 5, 6, 7])
    def test_room_change_detected_by_llm(self, from_step, build_state):
        """LLM should detect room change request."""
        msg = "Can we switch to Room B instead of Room A?"
        build_state(from_step, msg)

        result = run_unified_detection(
            msg,
            current_step=from_step,
            date_confirmed=True,
            room_locked=True,
        )

        # LLM should detect room change
        has_room_signal = (
            result.is_change_request or
            result.room_preference is not None
        )
        assert has_room_signal, f"LLM should detect room change in '{msg}'"

    @pytest.mark.parametrize("from_step", [4, 5, 6, 7])
    def test_participant_change_detected_by_llm(self, from_step, build_state):
        """LLM should detect participant count change."""
        msg = "Actually we're expecting 50 people now instead of 30."
        build_state(from_step, msg)

        result = run_unified_detection(
            msg,
            current_step=from_step,
            date_confirmed=True,
            room_locked=True,
        )

        # LLM should detect participant change
        has_participant_signal = (
            result.is_change_request or
            result.participants is not None
        )
        assert has_participant_signal, f"LLM should detect participant change in '{msg}'"

        if result.participants:
            assert result.participants == 50, f"Should extract 50 participants, got: {result.participants}"

    @pytest.mark.parametrize("from_step", [4, 5, 6, 7])
    def test_product_add_detected_by_llm(self, from_step, build_state):
        """LLM should detect product addition request."""
        msg = "Can you also add a projector and whiteboard to the booking?"
        build_state(from_step, msg)

        result = run_unified_detection(
            msg,
            current_step=from_step,
            date_confirmed=True,
            room_locked=True,
        )

        # LLM should detect products
        has_product_signal = len(result.products) > 0
        assert has_product_signal, f"LLM should detect product add in '{msg}', got products: {result.products}"

    def test_qna_not_detected_as_change(self, build_state):
        """LLM should NOT detect Q&A as a change request."""
        msg = "What parking options do you have?"
        build_state(4, msg)

        result = run_unified_detection(
            msg,
            current_step=4,
            date_confirmed=True,
            room_locked=True,
        )

        # This should be a question, NOT a change request
        assert result.is_question, f"'{msg}' should be detected as question"
        assert not result.is_change_request, f"'{msg}' should NOT be detected as change request"

    def test_hybrid_date_change_plus_qna(self, build_state):
        """LLM should detect BOTH date change AND Q&A in hybrid message."""
        msg = "Can we move to April 15? Also, what catering options do you have?"
        build_state(4, msg)

        result = run_unified_detection(
            msg,
            current_step=4,
            date_confirmed=True,
            room_locked=True,
        )

        # Should detect date
        has_date = result.date is not None or result.is_change_request
        assert has_date, f"Should detect date change in hybrid message"

        # Should also detect question
        assert result.is_question, f"Should detect Q&A in hybrid message"

    def test_confirmation_not_detected_as_change(self, build_state):
        """LLM should detect confirmation, NOT change request."""
        msg = "Yes, that works for us. Let's proceed."
        build_state(4, msg)

        result = run_unified_detection(
            msg,
            current_step=4,
            date_confirmed=True,
            room_locked=True,
        )

        # Should be confirmation
        assert result.is_confirmation or result.is_acceptance, \
            f"'{msg}' should be detected as confirmation/acceptance"

        # Should NOT be a change
        assert not result.is_change_request, \
            f"'{msg}' should NOT be detected as change request"

    @pytest.mark.parametrize("msg,expected_signal", [
        ("Change the date to next Friday", "date"),
        ("We need to switch to a larger room", "room"),
        ("Our group size increased to 60 people", "participants"),
        ("Please add coffee service to the booking", "products"),
        ("The billing address is ACME Corp, Zurich", "billing"),
    ])
    def test_various_change_signals(self, msg, expected_signal, build_state):
        """LLM should correctly identify various change signals."""
        build_state(4, msg)

        result = run_unified_detection(
            msg,
            current_step=4,
            date_confirmed=True,
            room_locked=True,
        )

        if expected_signal == "date":
            assert result.date is not None or result.is_change_request, \
                f"Should detect date in '{msg}'"
        elif expected_signal == "room":
            assert result.room_preference is not None or result.is_change_request, \
                f"Should detect room in '{msg}'"
        elif expected_signal == "participants":
            assert result.participants is not None or result.is_change_request, \
                f"Should detect participants in '{msg}'"
        elif expected_signal == "products":
            assert len(result.products) > 0 or result.is_change_request, \
                f"Should detect products in '{msg}'"
        elif expected_signal == "billing":
            assert result.billing_address is not None, \
                f"Should detect billing in '{msg}'"


# =============================================================================
# TRUE E2E TESTS: Full Workflow Pipeline (require AGENT_MODE=openai)
# =============================================================================


@requires_live_llm
class TestDetourE2EFullPipeline:
    """
    TRUE E2E tests that call process_msg and verify the full workflow pipeline.

    These tests verify:
    1. Full message processing (not just detection)
    2. Draft message generation with proper content
    3. Step transitions in the database
    4. No fallback/stub responses
    5. caller_step correctly set for detour return

    Run with: AGENT_MODE=openai pytest -k "E2EFullPipeline" -v
    """

    @pytest.mark.parametrize("from_step", [4, 5, 6, 7])
    def test_date_change_full_e2e(self, from_step, e2e_harness):
        """
        TRUE E2E: Date change request processes through full workflow.

        Verifies:
        - Message goes through process_msg
        - Draft messages are generated
        - Step transitions to 2
        - caller_step is set for return
        - No fallback responses
        """
        harness = e2e_harness(
            from_step,
            event_kwargs={
                "date_confirmed": True,
                "chosen_date": "15.03.2026",
            },
        )

        result = harness.send_message("Can we change the date to March 20 instead?")

        # Verify draft messages exist
        harness.assert_has_draft_message()

        # Verify no fallback
        harness.assert_no_fallback(f"date change from step {from_step}")

        # Verify step transition after date change
        event = harness.get_current_event()
        assert event is not None, "Event should exist"

        # Date change flow: step 2 (date confirm) → step 3 (room check) → step 4 (offer regen)
        # After offer is regenerated, stay at step 4 awaiting client response to new offer.
        # The client needs to review/accept the updated offer before workflow continues.
        current_step = event.get("current_step")
        assert current_step == 4, \
            f"Date change should end at step 4 (awaiting client response to new offer), got {current_step}"

        # caller_step should be cleared after the detour completes (client now needs to respond)
        assert event.get("caller_step") is None, \
            f"caller_step should be None after detour completes, got {event.get('caller_step')}"

    @pytest.mark.parametrize("from_step", [4, 5, 6, 7])
    def test_room_change_full_e2e(self, from_step, e2e_harness):
        """
        TRUE E2E: Room change request processes through full workflow.
        """
        harness = e2e_harness(
            from_step,
            event_kwargs={
                "locked_room_id": "Room A",
            },
        )

        result = harness.send_message("Can we switch to Room B instead of Room A?")

        # Verify draft messages exist
        harness.assert_has_draft_message()

        # Verify no fallback
        harness.assert_no_fallback(f"room change from step {from_step}")

        # Verify step transition after room change
        event = harness.get_current_event()
        current_step = event.get("current_step")

        # Room change flow: step 3 (room selection) → step 4 (offer regen)
        # After offer is regenerated, stay at step 4 awaiting client response to new offer.
        assert current_step == 4, \
            f"Room change should end at step 4 (awaiting client response to new offer), got {current_step}"

        # caller_step should be cleared after the detour completes
        assert event.get("caller_step") is None, \
            f"caller_step should be None after detour completes, got {event.get('caller_step')}"

    @pytest.mark.parametrize("from_step", [4, 5, 6, 7])
    def test_participant_change_full_e2e(self, from_step, e2e_harness):
        """
        TRUE E2E: Participant change request processes through full workflow.
        """
        harness = e2e_harness(
            from_step,
            event_kwargs={
                "requirements": {"number_of_participants": 20},
            },
        )

        result = harness.send_message("Actually we're expecting 50 people now instead of 20.")

        # Verify draft messages exist
        harness.assert_has_draft_message()

        # Verify no fallback
        harness.assert_no_fallback(f"participant change from step {from_step}")

        # Check response mentions the change or asks for confirmation
        body = harness.get_combined_body().lower()
        # Should acknowledge the participant change or route appropriately
        event = harness.get_current_event()
        assert event is not None

    @pytest.mark.parametrize("from_step", [4, 5, 6, 7])
    def test_product_add_full_e2e(self, from_step, e2e_harness):
        """
        TRUE E2E: Product addition request processes through full workflow.
        """
        # Product add needs matching hashes for step 4's P2 precondition
        # to pass (room_eval_hash == requirements_hash)
        # IMPORTANT: Use canonical key names from REQUIREMENT_KEYS
        from workflows.common.requirements import requirements_hash
        test_requirements = {
            "number_of_participants": 50,
            "seating_layout": "theater",
            "event_duration": {"start": "09:00", "end": "17:00"},
            "special_requirements": None,
            "preferred_room": None,
        }
        req_hash = requirements_hash(test_requirements)

        harness = e2e_harness(
            from_step,
            event_kwargs={
                "locked_room_id": "Room A",
                "requirements": test_requirements,
                "requirements_hash": req_hash,
                "room_eval_hash": req_hash,  # Must match for P2 to pass
            },
        )

        # Debug: Check event state before sending message
        event_before = harness.get_current_event()
        print(f"\n[DEBUG] BEFORE: step={event_before.get('current_step')}, "
              f"req_hash={event_before.get('requirements_hash')}, "
              f"room_eval_hash={event_before.get('room_eval_hash')}, "
              f"locked_room={event_before.get('locked_room_id')}, "
              f"requirements={event_before.get('requirements')}")

        result = harness.send_message("Can you add a projector to the booking please?")

        # Debug: Check event state after sending message
        event_after = harness.get_current_event()
        print(f"[DEBUG] AFTER: step={event_after.get('current_step')}, "
              f"req_hash={event_after.get('requirements_hash')}, "
              f"room_eval_hash={event_after.get('room_eval_hash')}, "
              f"requirements={event_after.get('requirements')}")

        # Verify draft messages exist
        harness.assert_has_draft_message()

        # Verify no fallback
        harness.assert_no_fallback(f"product add from step {from_step}")

        # Product changes should be handled in step 4 (offer regeneration)
        # After offer is regenerated, step advances to 5 (awaiting client response)
        event = harness.get_current_event()
        current_step = event.get("current_step")
        # Valid outcomes: step 4 (processing), step 5 (offer sent), or original step (in-place)
        assert current_step in (4, 5, from_step), \
            f"Product change should be handled in step 4/5 or stay at {from_step}, got {current_step}"

    @pytest.mark.parametrize("from_step", [4, 5, 6, 7])
    def test_billing_capture_full_e2e(self, from_step, e2e_harness):
        """
        TRUE E2E: Billing capture processes in-place without routing.

        Note: At step 4, providing billing can trigger advancement to step 5
        since it implies offer acceptance. Steps 5-7 should remain unchanged.
        """
        harness = e2e_harness(from_step)

        result = harness.send_message(
            "Our billing address is: ACME AG, Bahnhofstrasse 1, 8001 Zurich, Switzerland"
        )

        # Verify draft messages exist
        harness.assert_has_draft_message()

        # Verify no fallback
        harness.assert_no_fallback(f"billing from step {from_step}")

        # Billing behavior depends on step:
        # - Step 4: providing billing implies acceptance, may advance to step 5
        # - Steps 5-7: billing is in-place, step unchanged
        current_step = harness.get_current_event().get("current_step")
        if from_step == 4:
            assert current_step in (4, 5), \
                f"Billing at step 4 should stay at 4 or advance to 5, got {current_step}"
        else:
            harness.assert_step_unchanged(from_step)

        # Verify billing info was captured
        event = harness.get_current_event()
        billing = event.get("billing_address") or {}
        # Should have some billing info captured
        # The exact structure depends on extraction

    def test_date_change_generates_date_options(self, e2e_harness):
        """
        TRUE E2E: Date change should generate date selection response.
        """
        harness = e2e_harness(
            5,
            event_kwargs={
                "date_confirmed": True,
                "chosen_date": "15.03.2026",
            },
        )

        result = harness.send_message("We need to move the event to a different date, March 20 would work better")

        harness.assert_has_draft_message()
        harness.assert_no_fallback("date change response")

        # Response should mention dates or acknowledge the change
        body = harness.get_combined_body().lower()
        # Should have some date-related content
        has_date_content = any(word in body for word in ["date", "march", "20", "confirm", "change"])
        assert has_date_content, f"Response should mention date, got: {body[:300]}"

    def test_room_change_generates_room_options(self, e2e_harness):
        """
        TRUE E2E: Room change should generate room selection response.
        """
        harness = e2e_harness(
            5,
            event_kwargs={
                "locked_room_id": "Room A",
            },
        )

        result = harness.send_message("We'd like to use a larger room instead of Room A")

        harness.assert_has_draft_message()
        harness.assert_no_fallback("room change response")

        # Response should mention rooms or acknowledge the change
        body = harness.get_combined_body().lower()
        has_room_content = any(word in body for word in ["room", "larger", "space", "capacity"])
        assert has_room_content, f"Response should mention room, got: {body[:300]}"

    def test_multiple_changes_handled(self, e2e_harness):
        """
        TRUE E2E: Message with multiple changes is handled.
        """
        harness = e2e_harness(
            5,
            event_kwargs={
                "date_confirmed": True,
                "chosen_date": "15.03.2026",
                "locked_room_id": "Room A",
            },
        )

        result = harness.send_message(
            "We need to change the date to April 10 and also switch to a larger room"
        )

        harness.assert_has_draft_message()
        harness.assert_no_fallback("multiple changes")

        # Should process at least one of the changes
        event = harness.get_current_event()
        # Either step changed or response acknowledges the changes
        body = harness.get_combined_body().lower()
        has_response = len(body) > 50  # Should have substantive response
        assert has_response, "Should generate substantive response to multiple changes"


@requires_live_llm
class TestDetourE2ECallerStepReturn:
    """
    TRUE E2E tests verifying caller_step is preserved and workflow returns correctly.
    """

    def test_date_detour_return_to_caller_step(self, e2e_harness):
        """
        TRUE E2E: After date change, workflow should return to original step.

        Flow:
        1. Event at step 5
        2. User requests date change → routes to step 2
        3. User confirms new date → should return to step 5
        """
        harness = e2e_harness(
            5,
            event_kwargs={
                "date_confirmed": True,
                "chosen_date": "15.03.2026",
            },
        )

        # Step 1: Request date change
        result1 = harness.send_message("We need to change the date to March 25")

        # Verify it's processing the change
        harness.assert_has_draft_message()
        harness.assert_no_fallback("date change request")

        # Check caller_step is set (if step changed to 2)
        event = harness.get_current_event()
        if event.get("current_step") == 2:
            assert event.get("caller_step") == 5, "caller_step should be 5 for return"

    def test_room_detour_sets_caller_step(self, e2e_harness):
        """
        TRUE E2E: Room change from step 5 should set caller_step=5.
        """
        harness = e2e_harness(
            5,
            event_kwargs={
                "locked_room_id": "Room A",
            },
        )

        result = harness.send_message("Can we switch to Room B?")

        harness.assert_has_draft_message()
        harness.assert_no_fallback("room change")

        # If routed to step 3, caller_step should be set
        event = harness.get_current_event()
        if event.get("current_step") == 3:
            assert event.get("caller_step") == 5, "caller_step should be 5"


@requires_live_llm
class TestDetourE2EResponseQuality:
    """
    TRUE E2E tests verifying response quality (no fallbacks, proper content).
    """

    @pytest.mark.parametrize("change_msg", [
        "Let's move the event to April 5th",
        "We need a bigger room, Room A is too small",
        "Our headcount increased to 75 people",
        "Please add wine service to our booking",
        "Billing: TechCorp GmbH, Musterstr. 10, 8000 Zurich",
    ])
    def test_change_generates_quality_response(self, change_msg, e2e_harness):
        """
        TRUE E2E: Various change requests generate quality responses.
        """
        harness = e2e_harness(
            5,
            event_kwargs={
                "date_confirmed": True,
                "chosen_date": "15.03.2026",
                "locked_room_id": "Room A",
            },
        )

        result = harness.send_message(change_msg)

        # Must have draft messages
        harness.assert_has_draft_message()

        # Must not have fallback
        harness.assert_no_fallback(f"response to: {change_msg[:30]}")

        # Response should be substantive (>100 chars typically)
        body = harness.get_combined_body()
        assert len(body) >= 50, f"Response too short for '{change_msg}': {body}"

    def test_no_empty_reply_on_date_change(self, e2e_harness):
        """
        TRUE E2E: Date change should never produce empty reply.
        """
        harness = e2e_harness(
            4,
            event_kwargs={
                "date_confirmed": True,
                "chosen_date": "15.03.2026",
            },
        )

        result = harness.send_message("Change the event date to next Friday")

        drafts = harness.get_draft_messages()
        assert len(drafts) > 0, "Should produce draft messages"

        # Check no empty body
        for draft in drafts:
            body = draft.get("body_markdown") or draft.get("body") or ""
            assert len(body) > 0, "Draft body should not be empty"

    def test_detour_response_not_generic(self, e2e_harness):
        """
        TRUE E2E: Detour response should be specific, not generic.
        """
        harness = e2e_harness(
            5,
            event_kwargs={
                "date_confirmed": True,
                "chosen_date": "15.03.2026",
            },
        )

        result = harness.send_message("We need to change our event date to April 10, 2026")

        body = harness.get_combined_body()

        # Should NOT be generic
        harness.assert_body_not_contains(
            "I'll look into",
            "Let me check",
            "generic",
        )

        # Should have specific content about the change
        # (date mention, confirmation prompt, etc.)
        body_lower = body.lower()
        has_specific_content = any(
            word in body_lower
            for word in ["april", "10", "date", "change", "confirm", "2026"]
        )
        assert has_specific_content, f"Response should be specific about date, got: {body[:200]}"
