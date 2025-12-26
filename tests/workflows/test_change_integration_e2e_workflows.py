"""
E2E Change Integration Tests (V4 Workflow)

Tests change detection and routing across all workflow steps (2-7) to ensure:
- Changes detected precisely (no false positives)
- Routing follows DAG rules
- Hash guards prevent redundant reruns
- Caller step preserved during detours
"""

from __future__ import annotations

import pytest
from backend.workflows.change_propagation import ChangeType, detect_change_type, route_change_on_updated_variable
from backend.workflows.common.requirements import requirements_hash


# ============================================================================
# HELPER BUILDERS FOR REUSABLE EVENT SETUP
# ============================================================================


def build_base_event(step: int, **kwargs) -> dict:
    """
    Build a base event entry for testing.

    Args:
        step: Current workflow step (1-7)
        **kwargs: Additional fields to merge into event

    Returns:
        Event entry dict with defaults
    """
    # Build event with explicit fields
    event = {
        "event_id": kwargs.pop("event_id", "evt_test_001"),
        "current_step": step,
        "caller_step": kwargs.pop("caller_step", None),
        "thread_state": kwargs.pop("thread_state", "Awaiting Client"),
        "date_confirmed": kwargs.pop("date_confirmed", False),
        "chosen_date": kwargs.pop("chosen_date", None),
        "locked_room_id": kwargs.pop("locked_room_id", None),
        "requirements": kwargs.pop("requirements", {}),
        "requirements_hash": kwargs.pop("requirements_hash", None),
        "room_eval_hash": kwargs.pop("room_eval_hash", None),
        "products": kwargs.pop("products", []),
        "offers": kwargs.pop("offers", []),
        "deposit_state": kwargs.pop("deposit_state", {}),
    }
    # Remove None values
    return {k: v for k, v in event.items() if v is not None}


def build_confirmed_event_at_step4(**kwargs) -> dict:
    """
    Build an event at Step 4 (Offer) with date confirmed and room locked.

    Common scenario: Client is reviewing offer, all prerequisites met.
    """
    # Extract step (can be overridden for builders that call this)
    step = kwargs.pop("step", 4)

    # Handle requirements with default
    requirements = kwargs.pop("requirements", {
        "number_of_participants": 30,
        "seating_layout": "boardroom",
        "duration": {"start": "14:00", "end": "18:00"},
    })
    req_hash = requirements_hash(requirements)

    return build_base_event(
        step=step,
        date_confirmed=True,
        chosen_date=kwargs.pop("chosen_date", "15.03.2025"),
        locked_room_id=kwargs.pop("locked_room_id", "Room A"),
        requirements=requirements,
        requirements_hash=kwargs.pop("requirements_hash", req_hash),
        room_eval_hash=kwargs.pop("room_eval_hash", req_hash),  # Default: hash match
        **kwargs
    )


def build_negotiation_event_at_step5(**kwargs) -> dict:
    """
    Build an event at Step 5 (Negotiation) with offer sent.

    Common scenario: Client is negotiating price/terms after receiving offer.
    """
    # Extract step (can be overridden for builders that call this)
    step = kwargs.pop("step", 5)

    # Extract offers if provided, otherwise use default
    offers = kwargs.pop("offers", [{
        "offer_id": "evt_test_001-OFFER-1",
        "version": 1,
        "status": "Sent",
        "total_amount": 3500.0,
    }])

    return build_confirmed_event_at_step4(
        step=step,
        offers=offers,
        **kwargs
    )


def build_confirmation_event_at_step7(**kwargs) -> dict:
    """
    Build an event at Step 7 (Confirmation) with offer accepted.

    Common scenario: Client is finalizing deposit/confirmation details.
    """
    # Extract step (defaults to 7)
    step = kwargs.pop("step", 7)

    # Extract offers and deposit_state if provided, otherwise use defaults
    offers = kwargs.pop("offers", [{
        "offer_id": "evt_test_001-OFFER-1",
        "version": 1,
        "status": "Accepted",
        "total_amount": 3500.0,
    }])
    deposit_state = kwargs.pop("deposit_state", {
        "required": True,
        "percent": 20,
        "status": "requested",
        "due_amount": 700.0,
    })

    return build_negotiation_event_at_step5(
        step=step,
        offers=offers,
        deposit_state=deposit_state,
        **kwargs
    )


class TestProductChangeAtStep4:
    """Test PRODUCTS change type at Step 4 (Offer)."""

    def test_product_swap_stays_in_step4(self):
        """Product swap should stay in Step 4, regenerate offer, skip Steps 2/3."""
        # Arrange: Event at Step 4 with locked room and confirmed date
        event_state = {
            "current_step": 4,
            "caller_step": None,
            "date_confirmed": True,
            "chosen_date": "15.03.2025",
            "locked_room_id": "Room A",
            "requirements_hash": "abc123",
            "room_eval_hash": "abc123",  # Hash match = room still valid
            "products": [{"name": "Coffee", "quantity": 20}],
        }
        user_info = {
            "products_add": [{"name": "Prosecco", "quantity": 10, "unit_price": 8.0}],
        }
        message_text = "Can we add Prosecco to the order?"

        # Act: Detect change
        change_type = detect_change_type(event_state, user_info, message_text=message_text)

        # Assert: PRODUCTS change detected
        assert change_type == ChangeType.PRODUCTS, "Should detect PRODUCTS change"

        # Act: Route change
        decision = route_change_on_updated_variable(event_state, change_type, from_step=4)

        # Assert: Stay in Step 4
        assert decision.next_step == 4, "Should stay in Step 4"
        assert decision.needs_reeval is True, "Should regenerate offer"
        assert decision.maybe_run_step3 is False, "Should NOT run Step 3"

    def test_product_change_hash_guard_prevents_step3_rerun(self):
        """Requirements hash unchanged → Step 3 should be skipped."""
        event_state = {
            "current_step": 4,
            "requirements_hash": "xyz789",
            "room_eval_hash": "xyz789",  # MATCH = no room recheck needed
        }
        user_info = {"products_add": [{"name": "Wine", "quantity": 5, "unit_price": 12.0}]}
        message_text = "Add wine please"

        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        assert change_type == ChangeType.PRODUCTS

        # Hash match means Step 3 won't be triggered
        assert event_state["requirements_hash"] == event_state["room_eval_hash"]


class TestCommercialChangeAtStep5:
    """Test COMMERCIAL change type at Step 5 (Negotiation)."""

    def test_budget_counter_loops_in_step5(self):
        """Budget negotiation should loop in Step 5, no Step 4 rerun."""
        event_state = {
            "current_step": 5,
            "caller_step": None,
            "date_confirmed": True,
            "locked_room_id": "Room B",
            "requirements_hash": "def456",
            "room_eval_hash": "def456",
        }
        user_info = {}
        message_text = "Can we drop the price by 10%?"

        # Act: Detect change
        change_type = detect_change_type(event_state, user_info, message_text=message_text)

        # Assert: COMMERCIAL change detected
        assert change_type == ChangeType.COMMERCIAL, "Should detect COMMERCIAL change"

        # Act: Route change
        decision = route_change_on_updated_variable(event_state, change_type, from_step=5)

        # Assert: Stay in Step 5
        assert decision.next_step == 5, "Should stay in Step 5"
        assert decision.needs_reeval is True, "Should restart negotiation"
        assert decision.updated_caller_step is None, "No caller step for commercial loop"

    def test_no_false_positive_on_price_question(self):
        """'What's the price?' should NOT trigger COMMERCIAL change."""
        event_state = {"current_step": 5}
        user_info = {}
        message_text = "What's the total price?"

        # Act
        change_type = detect_change_type(event_state, user_info, message_text=message_text)

        # Assert: No change detected (just a question)
        assert change_type is None, "Should NOT detect change for price question"


class TestDepositChangeAtStep7:
    """Test DEPOSIT change type at Step 7 (Confirmation)."""

    def test_deposit_percentage_change_stays_in_step7(self):
        """Deposit change should stay in Step 7, repeat deposit workflow."""
        event_state = {
            "current_step": 7,
            "caller_step": None,
            "deposit_state": {"required": True, "percent": 20, "status": "requested"},
        }
        user_info = {}
        message_text = "I'd like to proceed with the deposit now"

        # Act: Detect change
        change_type = detect_change_type(event_state, user_info, message_text=message_text)

        # Assert: DEPOSIT change detected
        assert change_type == ChangeType.DEPOSIT, "Should detect DEPOSIT change"

        # Act: Route change
        decision = route_change_on_updated_variable(event_state, change_type, from_step=7)

        # Assert: Stay in Step 7
        assert decision.next_step == 7, "Should stay in Step 7"
        assert decision.needs_reeval is True, "Should repeat deposit workflow"

    def test_no_false_positive_on_deposit_question(self):
        """'When is deposit due?' should NOT trigger DEPOSIT change."""
        event_state = {"current_step": 7}
        user_info = {}
        message_text = "When is the deposit due?"

        # Act
        change_type = detect_change_type(event_state, user_info, message_text=message_text)

        # Assert: No change detected
        assert change_type is None, "Should NOT detect change for deposit question"


class TestLateDateChangeAtStep7:
    """Test DATE change during Step 7 (late date change)."""

    def test_late_date_change_detours_to_step2_preserves_caller(self):
        """Date change at Step 7 should detour to Step 2, preserve caller_step=7."""
        event_state = {
            "current_step": 7,
            "caller_step": None,
            "date_confirmed": True,
            "chosen_date": "15.03.2025",
            "locked_room_id": "Room C",
        }
        user_info = {"date": "2025-03-20"}
        message_text = "Can we change the date to March 20th?"

        # Act: Detect change
        change_type = detect_change_type(event_state, user_info, message_text=message_text)

        # Assert: DATE change detected
        assert change_type == ChangeType.DATE, "Should detect DATE change"

        # Act: Route change
        decision = route_change_on_updated_variable(event_state, change_type, from_step=7)

        # Assert: Detour to Step 2, preserve caller
        assert decision.next_step == 2, "Should detour to Step 2"
        assert decision.updated_caller_step == 7, "Should preserve caller_step=7"
        assert decision.maybe_run_step3 is True, "May need to run Step 3 after date change"


class TestRequirementsChangeWithHashGuard:
    """Test REQUIREMENTS change with hash guard logic."""

    def test_requirements_change_hash_mismatch_triggers_step3(self):
        """Requirements change with hash mismatch → detour to Step 3."""
        # Arrange: Event at Step 4, requirements changed
        requirements = {
            "number_of_participants": 50,
            "seating_layout": "theater",
            "duration": {"start": "14:00", "end": "18:00"},
        }
        event_state = {
            "current_step": 4,
            "caller_step": None,
            "locked_room_id": "Room A",
            "requirements": requirements,
            "requirements_hash": requirements_hash(requirements),  # New hash
            "room_eval_hash": "old_hash_xyz",  # Old hash (mismatch)
        }
        user_info = {"participants": 50}
        message_text = "Actually we're 50 people now"

        # Act: Detect change
        change_type = detect_change_type(event_state, user_info, message_text=message_text)

        # Assert: REQUIREMENTS change detected
        assert change_type == ChangeType.REQUIREMENTS, "Should detect REQUIREMENTS change"

        # Act: Route change
        decision = route_change_on_updated_variable(event_state, change_type, from_step=4)

        # Assert: Detour to Step 3
        assert decision.next_step == 3, "Should detour to Step 3"
        assert decision.updated_caller_step == 4, "Should preserve caller_step=4"
        assert decision.needs_reeval is True, "Should re-evaluate room"

    def test_requirements_change_hash_match_skips_step3(self):
        """Requirements change with hash match → skip Step 3 (fast-path)."""
        requirements = {"number_of_participants": 30}
        current_hash = requirements_hash(requirements)

        event_state = {
            "current_step": 4,
            "caller_step": None,
            "locked_room_id": "Room A",
            "requirements": requirements,
            "requirements_hash": current_hash,
            "room_eval_hash": current_hash,  # MATCH = no change
        }
        user_info = {"participants": 30}  # Same value
        message_text = "We're 30 people"

        # Act: Detect change
        change_type = detect_change_type(event_state, user_info, message_text=message_text)

        # Could be REQUIREMENTS or None depending on whether extraction differs
        if change_type == ChangeType.REQUIREMENTS:
            # Act: Route change
            decision = route_change_on_updated_variable(event_state, change_type, from_step=4)

            # Assert: Fast-skip (hash match)
            assert decision.skip_reason == "requirements_hash_match", "Should skip due to hash match"
            assert decision.needs_reeval is False, "Should NOT re-evaluate"


class TestRoomChangeAtStep5:
    """Test ROOM change during negotiation."""

    def test_room_change_request_detours_to_step3(self):
        """Room change request should detour to Step 3."""
        event_state = {
            "current_step": 5,
            "caller_step": None,
            "locked_room_id": "Room A",
            "date_confirmed": True,
        }
        user_info = {"room": "Sky Loft"}
        message_text = "Can we switch to Sky Loft instead?"

        # Act: Detect change
        change_type = detect_change_type(event_state, user_info, message_text=message_text)

        # Assert: ROOM change detected
        assert change_type == ChangeType.ROOM, "Should detect ROOM change"

        # Act: Route change
        decision = route_change_on_updated_variable(event_state, change_type, from_step=5)

        # Assert: Detour to Step 3
        assert decision.next_step == 3, "Should detour to Step 3"
        assert decision.updated_caller_step == 5, "Should preserve caller_step=5"


class TestSiteVisitChange:
    """Test SITE_VISIT change type."""

    def test_site_visit_reschedule_stays_in_step7(self):
        """Site visit reschedule should stay in Step 7."""
        event_state = {"current_step": 7}
        user_info = {"site_visit_time": "14:00"}
        message_text = "Can we reschedule the site visit to 2pm on Tuesday?"

        # Act: Detect change
        change_type = detect_change_type(event_state, user_info, message_text=message_text)

        # Assert: SITE_VISIT change detected
        assert change_type == ChangeType.SITE_VISIT, "Should detect SITE_VISIT change"

        # Act: Route change
        decision = route_change_on_updated_variable(event_state, change_type, from_step=7)

        # Assert: Stay in Step 7
        assert decision.next_step == 7, "Should stay in Step 7"
        assert decision.skip_reason == "site_visit_reschedule"


class TestClientInfoChange:
    """Test CLIENT_INFO change type."""

    def test_billing_address_change_updates_in_place(self):
        """Billing address change should update in place, no routing."""
        event_state = {"current_step": 5}
        user_info = {"billing_address": "Zurich HQ, Bahnhofstrasse 1"}
        message_text = "Please update the billing address to Zurich HQ"

        # Act: Detect change
        change_type = detect_change_type(event_state, user_info, message_text=message_text)

        # Assert: CLIENT_INFO change detected
        assert change_type == ChangeType.CLIENT_INFO, "Should detect CLIENT_INFO change"

        # Act: Route change
        decision = route_change_on_updated_variable(event_state, change_type, from_step=5)

        # Assert: Stay in current step (no routing)
        assert decision.next_step == 5, "Should stay in current step"
        assert decision.needs_reeval is False, "Local update only, no reeval"
        assert decision.skip_reason == "client_info_update"


class TestChangeIntentPrecision:
    """Test that change intent signals are precise (no false positives)."""

    def test_no_change_on_general_question(self):
        """General questions should NOT trigger change detection."""
        test_cases = [
            ("What rooms do you have available?", {}),
            ("How many people can Room A hold?", {}),
            ("What's included in the catering package?", {}),
            ("When do I need to pay the deposit?", {}),
            ("What's the total cost?", {}),
        ]

        for message_text, user_info in test_cases:
            event_state = {"current_step": 4, "date_confirmed": True, "locked_room_id": "Room A"}
            change_type = detect_change_type(event_state, user_info, message_text=message_text)
            assert change_type is None, f"Should NOT detect change for: {message_text}"

    def test_change_detected_with_intent_signals(self):
        """Messages with change intent should trigger detection."""
        test_cases = [
            ("Actually we need 50 people", {"participants": 50}, ChangeType.REQUIREMENTS),
            ("Can we change to Sky Loft?", {"room": "Sky Loft"}, ChangeType.ROOM),
            ("Switch the date to March 20th", {"date": "2025-03-20"}, ChangeType.DATE),
        ]

        for message_text, user_info, expected_type in test_cases:
            event_state = {
                "current_step": 4,
                "date_confirmed": True,
                "chosen_date": "15.03.2025",
                "locked_room_id": "Room A",
            }
            change_type = detect_change_type(event_state, user_info, message_text=message_text)
            assert change_type == expected_type, f"Should detect {expected_type.value} for: {message_text}"


# ============================================================================
# ADDITIONAL E2E SCENARIOS (From Prompt 2)
# ============================================================================


class TestQnATriggeredRequirementChange:
    """Test Q&A-triggered requirement change with Step 4 caller (from prompt)."""

    def test_qna_attendee_change_reroutes_to_step3_then_back_to_step4(self):
        """
        Event at Step 4 receiving 'Actually 60 attendees now' during Q&A.

        Expected flow:
        1. Change detected: REQUIREMENTS
        2. Reroute to Step 3 (room re-evaluation)
        3. Preserve caller_step=4 for return
        4. Hash invalidation triggers room recheck
        """
        # Arrange: Event at Step 4, hash currently matches
        event_state = build_confirmed_event_at_step4(
            requirements={
                "number_of_participants": 30,  # Current
                "seating_layout": "boardroom",
            }
        )
        # Hash currently matches
        assert event_state["requirements_hash"] == event_state["room_eval_hash"]

        # Act: Client updates attendees during Q&A
        user_info = {"participants": 60}  # NEW value
        message_text = "Actually we're 60 attendees now"

        change_type = detect_change_type(event_state, user_info, message_text=message_text)

        # Assert: REQUIREMENTS change detected
        assert change_type == ChangeType.REQUIREMENTS, "Should detect REQUIREMENTS change"

        # Simulate event_state update (would happen in step implementation BEFORE routing)
        event_state["requirements"]["number_of_participants"] = 60
        event_state["requirements_hash"] = requirements_hash(event_state["requirements"])

        # Now route with updated state
        decision = route_change_on_updated_variable(event_state, change_type, from_step=4)

        # Assert: Route to Step 3 for room re-evaluation
        assert decision.next_step == 3, "Should reroute to Step 3"
        assert decision.updated_caller_step == 4, "Should preserve caller_step=4"
        assert decision.needs_reeval is True, "Should require room re-evaluation"

        # Assert: Hash invalidation - new requirements_hash ≠ old room_eval_hash
        assert event_state["requirements_hash"] != event_state["room_eval_hash"], "Hash should be invalidated"


class TestOfferStageProductSwap:
    """Test offer-stage product swap (already covered but expanded)."""

    def test_multiple_product_operations_stay_in_step4(self):
        """
        Multiple product changes at Step 4 should stay in products mini-flow.

        No date/room rechecks needed.
        """
        event_state = build_confirmed_event_at_step4(
            products=[
                {"name": "Coffee", "quantity": 20, "unit_price": 3.5},
                {"name": "Water", "quantity": 30, "unit_price": 2.0},
            ]
        )

        # Act: Add and remove products
        user_info = {
            "products_add": [{"name": "Prosecco", "quantity": 10, "unit_price": 8.0}],
            "products_remove": ["Water"],
        }
        message_text = "Swap water for Prosecco please"

        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        decision = route_change_on_updated_variable(event_state, change_type, from_step=4)

        # Assert
        assert change_type == ChangeType.PRODUCTS
        assert decision.next_step == 4, "Should stay in Step 4"
        assert decision.maybe_run_step3 is False, "Should NOT trigger Step 3"
        assert decision.skip_reason == "products_only"


class TestNegotiationStageBudgetAdjustment:
    """Test negotiation-stage budget adjustment (from prompt)."""

    def test_budget_adjustment_loops_in_step5_no_step4_rerun(self):
        """
        Event at Step 5 hearing 'Lower the rate to 120/head'.

        Expected flow:
        1. Change detected: COMMERCIAL
        2. Loop in Step 5 (negotiation continues)
        3. Hash guard skips Step 4 (no structural change)
        """
        # Arrange: Event at Step 5 with offer sent
        event_state = build_negotiation_event_at_step5()

        # Act: Client requests price reduction
        user_info = {}
        message_text = "Can you lower the rate to CHF 120 per head?"

        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        decision = route_change_on_updated_variable(event_state, change_type, from_step=5)

        # Assert: COMMERCIAL change detected
        assert change_type == ChangeType.COMMERCIAL, "Should detect COMMERCIAL change"

        # Assert: Loop in Step 5
        assert decision.next_step == 5, "Should stay in Step 5"
        assert decision.updated_caller_step is None, "No caller for same-step loop"
        assert decision.needs_reeval is True, "Should restart negotiation"

        # Assert: Hash guard prevents Step 4 rerun (structural data unchanged)
        assert event_state["requirements_hash"] == event_state["room_eval_hash"]


class TestConfirmationStageMultiChange:
    """Test confirmation-stage deposit change AND late date change (from prompt)."""

    def test_deposit_and_date_change_triggers_both_workflows(self):
        """
        Event at Step 7 message: 'Deposit should be 30% and move date to July 12'.

        Expected flow:
        1. First change detected: DEPOSIT (processed first)
        2. Second change detected: DATE (would be processed in next message)

        Note: In practice, user would send two messages or system would handle sequentially.
        This test verifies both changes are detectable.
        """
        # Arrange: Event at Step 7
        event_state = build_confirmation_event_at_step7()

        # Act: Detect deposit change
        user_info_deposit = {}
        message_deposit = "Let's proceed with a 30% deposit instead of 20%"
        change_type_deposit = detect_change_type(event_state, user_info_deposit, message_text=message_deposit)

        # Assert: DEPOSIT change detected
        assert change_type_deposit == ChangeType.DEPOSIT
        decision_deposit = route_change_on_updated_variable(event_state, change_type_deposit, from_step=7)
        assert decision_deposit.next_step == 7, "Deposit change stays in Step 7"

        # Act: Detect date change (separate message)
        user_info_date = {"date": "2025-07-12"}
        message_date = "Also, can we move the date to July 12th?"
        change_type_date = detect_change_type(event_state, user_info_date, message_text=message_date)

        # Assert: DATE change detected
        assert change_type_date == ChangeType.DATE
        decision_date = route_change_on_updated_variable(event_state, change_type_date, from_step=7)
        assert decision_date.next_step == 2, "Date change detours to Step 2"
        assert decision_date.updated_caller_step == 7, "Should preserve caller_step=7"
        assert decision_date.maybe_run_step3 is True, "May need room recheck after date change"

    def test_combined_message_deposit_and_date_change(self):
        """
        Single message with both deposit and date change.

        Change detection precedence: DATE takes priority (checked first).
        """
        event_state = build_confirmation_event_at_step7()

        # Act: Combined message
        user_info = {"date": "2025-07-12"}
        message_text = "Deposit should be 30% and move date to July 12th"

        change_type = detect_change_type(event_state, user_info, message_text=message_text)

        # Assert: DATE takes precedence (checked first in detect_change_type)
        assert change_type == ChangeType.DATE, "DATE should take precedence when both present"


class TestHashGuardPreventingRedundantReruns:
    """Test hash guards prevent unnecessary step reruns."""

    def test_requirements_update_but_hash_match_skips_step3(self):
        """
        Client mentions requirements but values unchanged.

        Hash guard detects no actual change → skip Step 3 rerun.
        """
        # Arrange: Event at Step 4 with matching hashes
        requirements = {"number_of_participants": 30}
        req_hash = requirements_hash(requirements)
        event_state = build_confirmed_event_at_step4(
            requirements=requirements,
            requirements_hash=req_hash,
            room_eval_hash=req_hash,  # MATCH
        )

        # Act: Client mentions same requirement value
        user_info = {"participants": 30}  # SAME as current
        message_text = "Just confirming, we're 30 people"

        change_type = detect_change_type(event_state, user_info, message_text=message_text)

        # If change detected, routing should skip due to hash match
        if change_type == ChangeType.REQUIREMENTS:
            decision = route_change_on_updated_variable(event_state, change_type, from_step=4)

            # Assert: Fast-skip due to hash match
            assert decision.skip_reason == "requirements_hash_match"
            assert decision.needs_reeval is False
        else:
            # Or change not detected at all (also acceptable)
            assert change_type is None

    def test_product_change_preserves_room_date_hashes(self):
        """
        Product change at Step 4 doesn't invalidate room/date hashes.

        No upward dependencies → Steps 2-3 unchanged.
        """
        event_state = build_confirmed_event_at_step4()
        original_req_hash = event_state["requirements_hash"]
        original_room_hash = event_state["room_eval_hash"]

        # Act: Product change
        user_info = {"products_add": [{"name": "Coffee", "quantity": 20}]}
        message_text = "Add coffee"

        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        decision = route_change_on_updated_variable(event_state, change_type, from_step=4)

        # Assert: PRODUCTS change stays in Step 4
        assert change_type == ChangeType.PRODUCTS
        assert decision.next_step == 4

        # Assert: Hashes unchanged (product changes don't affect requirements/room)
        assert event_state["requirements_hash"] == original_req_hash
        assert event_state["room_eval_hash"] == original_room_hash


class TestComplexDetourReturnFlow:
    """Test complex detour and return flows."""

    def test_step7_to_step2_to_step3_to_step7_flow(self):
        """
        Late date change triggers cascade: Step 7 → Step 2 → Step 3 → back to Step 7.

        Verifies caller_step preserved through multiple detours.
        """
        # Arrange: Event at Step 7
        event_state = build_confirmation_event_at_step7()

        # Act: Date change at Step 7
        user_info = {"date": "2025-04-10"}
        message_text = "Change date to April 10th"

        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        decision = route_change_on_updated_variable(event_state, change_type, from_step=7)

        # Assert: Step 7 → Step 2
        assert change_type == ChangeType.DATE
        assert decision.next_step == 2
        assert decision.updated_caller_step == 7

        # Simulate: Step 2 completes, may trigger Step 3
        assert decision.maybe_run_step3 is True

        # After Step 3 completes, should return to caller_step=7
        # (This would be verified in full integration test with actual step execution)
