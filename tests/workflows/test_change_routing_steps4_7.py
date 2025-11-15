"""
Change Routing Unit Tests (Steps 4-7)

Tests the routing logic in route_change_on_updated_variable() to ensure:
- Correct next_step for each change type
- Caller step preservation during detours
- Hash guard skip conditions
- needs_reeval flags set correctly
"""

from __future__ import annotations

import pytest
from backend.workflows.change_propagation import (
    ChangeType,
    NextStepDecision,
    route_change_on_updated_variable,
)


class TestStep4RoutingLogic:
    """Test routing decisions at Step 4 (Offer)."""

    def test_products_change_stays_in_step4(self):
        """PRODUCTS change at Step 4 → stay in Step 4."""
        event_state = {"current_step": 4, "caller_step": None}

        decision = route_change_on_updated_variable(event_state, ChangeType.PRODUCTS, from_step=4)

        assert decision.next_step == 4
        assert decision.maybe_run_step3 is False
        assert decision.updated_caller_step is None
        assert decision.needs_reeval is True
        assert decision.skip_reason == "products_only"

    def test_date_change_detours_to_step2_from_step4(self):
        """DATE change at Step 4 → detour to Step 2, preserve caller."""
        event_state = {"current_step": 4, "caller_step": None}

        decision = route_change_on_updated_variable(event_state, ChangeType.DATE, from_step=4)

        assert decision.next_step == 2
        assert decision.maybe_run_step3 is True
        assert decision.updated_caller_step == 4
        assert decision.needs_reeval is True

    def test_room_change_detours_to_step3_from_step4(self):
        """ROOM change at Step 4 → detour to Step 3, preserve caller."""
        event_state = {"current_step": 4, "caller_step": None}

        decision = route_change_on_updated_variable(event_state, ChangeType.ROOM, from_step=4)

        assert decision.next_step == 3
        assert decision.maybe_run_step3 is False
        assert decision.updated_caller_step == 4
        assert decision.needs_reeval is True

    def test_requirements_change_hash_mismatch_detours_to_step3(self):
        """REQUIREMENTS change with hash mismatch → detour to Step 3."""
        event_state = {
            "current_step": 4,
            "caller_step": None,
            "requirements_hash": "new_hash_123",
            "room_eval_hash": "old_hash_456",  # MISMATCH
        }

        decision = route_change_on_updated_variable(event_state, ChangeType.REQUIREMENTS, from_step=4)

        assert decision.next_step == 3
        assert decision.updated_caller_step == 4
        assert decision.needs_reeval is True

    def test_requirements_change_hash_match_skips_step3(self):
        """REQUIREMENTS change with hash match → fast-skip, return to caller."""
        event_state = {
            "current_step": 4,
            "caller_step": 5,  # Previously came from Step 5
            "requirements_hash": "abc123",
            "room_eval_hash": "abc123",  # MATCH
        }

        decision = route_change_on_updated_variable(event_state, ChangeType.REQUIREMENTS, from_step=4)

        assert decision.next_step == 5  # Return to caller
        assert decision.updated_caller_step is None
        assert decision.skip_reason == "requirements_hash_match"
        assert decision.needs_reeval is False


class TestStep5RoutingLogic:
    """Test routing decisions at Step 5 (Negotiation)."""

    def test_commercial_change_stays_in_step5(self):
        """COMMERCIAL change at Step 5 → stay in Step 5."""
        event_state = {"current_step": 5, "caller_step": None}

        decision = route_change_on_updated_variable(event_state, ChangeType.COMMERCIAL, from_step=5)

        assert decision.next_step == 5
        assert decision.maybe_run_step3 is False
        assert decision.updated_caller_step is None
        assert decision.needs_reeval is True

    def test_date_change_detours_to_step2_from_step5(self):
        """DATE change at Step 5 → detour to Step 2, preserve caller."""
        event_state = {"current_step": 5, "caller_step": None}

        decision = route_change_on_updated_variable(event_state, ChangeType.DATE, from_step=5)

        assert decision.next_step == 2
        assert decision.updated_caller_step == 5
        assert decision.needs_reeval is True

    def test_room_change_detours_to_step3_from_step5(self):
        """ROOM change at Step 5 → detour to Step 3, preserve caller."""
        event_state = {"current_step": 5, "caller_step": None}

        decision = route_change_on_updated_variable(event_state, ChangeType.ROOM, from_step=5)

        assert decision.next_step == 3
        assert decision.updated_caller_step == 5
        assert decision.needs_reeval is True

    def test_products_change_detours_to_step4_from_step5(self):
        """PRODUCTS change at Step 5 → detour to Step 4 (products mini-flow)."""
        event_state = {"current_step": 5, "caller_step": None}

        decision = route_change_on_updated_variable(event_state, ChangeType.PRODUCTS, from_step=5)

        assert decision.next_step == 4
        assert decision.skip_reason == "products_only"
        assert decision.needs_reeval is True


class TestStep7RoutingLogic:
    """Test routing decisions at Step 7 (Confirmation)."""

    def test_deposit_change_stays_in_step7(self):
        """DEPOSIT change at Step 7 → stay in Step 7."""
        event_state = {"current_step": 7, "caller_step": None}

        decision = route_change_on_updated_variable(event_state, ChangeType.DEPOSIT, from_step=7)

        assert decision.next_step == 7
        assert decision.maybe_run_step3 is False
        assert decision.updated_caller_step is None
        assert decision.needs_reeval is True

    def test_site_visit_change_stays_in_step7(self):
        """SITE_VISIT change at Step 7 → stay in Step 7."""
        event_state = {"current_step": 7, "caller_step": None}

        decision = route_change_on_updated_variable(event_state, ChangeType.SITE_VISIT, from_step=7)

        assert decision.next_step == 7
        assert decision.maybe_run_step3 is False
        assert decision.skip_reason == "site_visit_reschedule"
        assert decision.needs_reeval is True

    def test_date_change_detours_to_step2_from_step7(self):
        """DATE change at Step 7 → detour to Step 2, preserve caller."""
        event_state = {"current_step": 7, "caller_step": None}

        decision = route_change_on_updated_variable(event_state, ChangeType.DATE, from_step=7)

        assert decision.next_step == 2
        assert decision.updated_caller_step == 7
        assert decision.maybe_run_step3 is True
        assert decision.needs_reeval is True

    def test_room_change_detours_to_step3_from_step7(self):
        """ROOM change at Step 7 → detour to Step 3, preserve caller."""
        event_state = {"current_step": 7, "caller_step": None}

        decision = route_change_on_updated_variable(event_state, ChangeType.ROOM, from_step=7)

        assert decision.next_step == 3
        assert decision.updated_caller_step == 7
        assert decision.needs_reeval is True

    def test_requirements_change_detours_to_step3_from_step7(self):
        """REQUIREMENTS change at Step 7 → detour to Step 3 if hash mismatch."""
        event_state = {
            "current_step": 7,
            "caller_step": None,
            "requirements_hash": "new_xyz",
            "room_eval_hash": "old_xyz",  # MISMATCH
        }

        decision = route_change_on_updated_variable(event_state, ChangeType.REQUIREMENTS, from_step=7)

        assert decision.next_step == 3
        assert decision.updated_caller_step == 7
        assert decision.needs_reeval is True


class TestClientInfoRouting:
    """Test CLIENT_INFO change routing (in-place updates)."""

    def test_client_info_stays_in_current_step(self):
        """CLIENT_INFO change → stay in current step, no routing."""
        for current_step in [2, 3, 4, 5, 7]:
            event_state = {"current_step": current_step, "caller_step": None}

            decision = route_change_on_updated_variable(
                event_state, ChangeType.CLIENT_INFO, from_step=current_step
            )

            assert decision.next_step == current_step, f"Should stay in Step {current_step}"
            assert decision.maybe_run_step3 is False
            assert decision.updated_caller_step is None
            assert decision.skip_reason == "client_info_update"
            assert decision.needs_reeval is False


class TestCallerStepPreservation:
    """Test that caller_step is preserved correctly during detours."""

    def test_caller_step_set_when_none(self):
        """If caller_step is None, set it to from_step during detour."""
        event_state = {"current_step": 4, "caller_step": None}

        decision = route_change_on_updated_variable(event_state, ChangeType.DATE, from_step=4)

        assert decision.updated_caller_step == 4, "Should set caller_step to from_step"

    def test_caller_step_preserved_when_already_set(self):
        """If caller_step already set, preserve it during detour."""
        event_state = {"current_step": 3, "caller_step": 5}  # Previously from Step 5

        decision = route_change_on_updated_variable(event_state, ChangeType.DATE, from_step=3)

        assert decision.updated_caller_step == 5, "Should preserve existing caller_step"

    def test_caller_step_not_set_for_same_step_routing(self):
        """If routing to same step, don't set caller_step."""
        event_state = {"current_step": 4, "caller_step": None}

        decision = route_change_on_updated_variable(event_state, ChangeType.PRODUCTS, from_step=4)

        assert decision.updated_caller_step is None, "Should not set caller for same-step routing"


class TestHashGuardLogic:
    """Test hash guard skip conditions."""

    def test_requirements_hash_match_triggers_skip(self):
        """Hash match → skip_reason set, needs_reeval=False."""
        event_state = {
            "current_step": 4,
            "caller_step": None,
            "requirements_hash": "match123",
            "room_eval_hash": "match123",
        }

        decision = route_change_on_updated_variable(event_state, ChangeType.REQUIREMENTS, from_step=4)

        assert decision.skip_reason == "requirements_hash_match"
        assert decision.needs_reeval is False

    def test_requirements_hash_mismatch_triggers_reeval(self):
        """Hash mismatch → no skip_reason, needs_reeval=True."""
        event_state = {
            "current_step": 4,
            "caller_step": None,
            "requirements_hash": "new456",
            "room_eval_hash": "old123",
        }

        decision = route_change_on_updated_variable(event_state, ChangeType.REQUIREMENTS, from_step=4)

        assert decision.skip_reason is None
        assert decision.needs_reeval is True

    def test_missing_hash_values_trigger_reeval(self):
        """Missing hash values → needs_reeval=True."""
        event_state = {
            "current_step": 4,
            "caller_step": None,
            "requirements_hash": None,
            "room_eval_hash": None,
        }

        decision = route_change_on_updated_variable(event_state, ChangeType.REQUIREMENTS, from_step=4)

        assert decision.needs_reeval is True


class TestComplexDetourScenarios:
    """Test complex multi-step detour scenarios."""

    def test_step7_date_change_may_trigger_step3(self):
        """Step 7 → Step 2 (date) → maybe Step 3 (room recheck)."""
        event_state = {"current_step": 7, "caller_step": None}

        decision = route_change_on_updated_variable(event_state, ChangeType.DATE, from_step=7)

        assert decision.next_step == 2
        assert decision.updated_caller_step == 7
        assert decision.maybe_run_step3 is True, "Date change may require room recheck"

    def test_step5_requirements_change_detours_to_step3_then_back(self):
        """Step 5 → Step 3 (requirements) → back to Step 5."""
        event_state = {
            "current_step": 5,
            "caller_step": None,
            "requirements_hash": "new",
            "room_eval_hash": "old",
        }

        decision = route_change_on_updated_variable(event_state, ChangeType.REQUIREMENTS, from_step=5)

        assert decision.next_step == 3
        assert decision.updated_caller_step == 5, "Should return to Step 5 after Step 3"

    def test_step4_products_no_upward_dependency(self):
        """Products change at Step 4 has no upward dependencies."""
        event_state = {"current_step": 4, "caller_step": None}

        decision = route_change_on_updated_variable(event_state, ChangeType.PRODUCTS, from_step=4)

        assert decision.next_step == 4
        assert decision.maybe_run_step3 is False, "Products don't affect room/date"
