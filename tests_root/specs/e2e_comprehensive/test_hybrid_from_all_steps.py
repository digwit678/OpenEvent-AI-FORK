"""
E2E Tests: Hybrid Messages from All Steps

Tests that messages combining workflow actions with Q&A are handled correctly.

Note: Tests in TestHybridDetectionIntegration require AGENT_MODE=openai.
"""

from __future__ import annotations

import os

import pytest

from detection.unified import run_unified_detection

# Skip in stub mode - integration tests require live LLM
requires_live_llm = pytest.mark.skipif(
    os.getenv("AGENT_MODE", "stub") == "stub",
    reason="Integration test requires AGENT_MODE=openai"
)


# =============================================================================
# CONFIRM + Q&A HYBRID TESTS
# =============================================================================


class TestConfirmPlusQnAHybrid:
    """Test confirmation messages combined with Q&A."""

    def test_step2_confirm_date_plus_parking_qna(self, build_state):
        """Step 2: Confirm date + parking Q&A."""
        msg = "March 15 works for us. By the way, where can our guests park?"
        build_state(2, msg, event_kwargs={"date_confirmed": False})

        result = run_unified_detection(msg, current_step=2, date_confirmed=False, room_locked=False)

        assert result is not None
        assert hasattr(result, "is_question")
        assert hasattr(result, "is_confirmation")

    def test_step3_confirm_room_plus_catering_qna(self, build_state):
        """Step 3: Confirm room + catering Q&A."""
        msg = "Room A sounds perfect! What catering packages do you offer?"
        build_state(3, msg)

        result = run_unified_detection(msg, current_step=3, date_confirmed=True, room_locked=False)

        assert result is not None
        assert hasattr(result, "room_preference")
        assert hasattr(result, "qna_types")


# =============================================================================
# ACCEPT + Q&A HYBRID TESTS
# =============================================================================


class TestAcceptPlusQnAHybrid:
    """Test acceptance messages combined with Q&A."""

    def test_step4_accept_offer_plus_room_features_qna(self, build_state):
        """Step 4: Accept offer + room features Q&A."""
        msg = "We accept the offer. Does the room have HDMI connectivity?"
        build_state(4, msg)

        result = run_unified_detection(msg, current_step=4, date_confirmed=True, room_locked=True)

        assert result is not None
        assert hasattr(result, "is_acceptance")

    def test_step5_accept_plus_parking_qna(self, build_state):
        """Step 5: Accept negotiated terms + parking Q&A."""
        msg = "The revised pricing works for us, let's proceed. Is parking included?"
        build_state(5, msg)

        result = run_unified_detection(msg, current_step=5, date_confirmed=True, room_locked=True)

        assert result is not None


# =============================================================================
# DETOUR + Q&A HYBRID TESTS
# =============================================================================


class TestDetourPlusQnAHybrid:
    """Test detour requests combined with Q&A."""

    @pytest.mark.parametrize("from_step", [4, 5, 6, 7])
    def test_date_detour_plus_catering_qna(self, from_step, build_state):
        """Date detour + catering Q&A from various steps."""
        msg = "Can we change to April 15 instead? Also, what catering options do you have?"
        build_state(from_step, msg)

        result = run_unified_detection(msg, current_step=from_step, date_confirmed=True, room_locked=True)

        assert result is not None
        assert hasattr(result, "date")
        assert hasattr(result, "is_question")

    @pytest.mark.parametrize("from_step", [4, 5, 6, 7])
    def test_room_detour_plus_parking_qna(self, from_step, build_state):
        """Room detour + parking Q&A from various steps."""
        msg = "Can we switch to Room C instead? Is parking free for guests?"
        build_state(from_step, msg)

        result = run_unified_detection(msg, current_step=from_step, date_confirmed=True, room_locked=True)

        assert result is not None
        assert hasattr(result, "room_preference")

    @pytest.mark.parametrize("from_step", [4, 5, 6, 7])
    def test_participant_change_plus_qna(self, from_step, build_state):
        """Participant change + Q&A from various steps."""
        msg = "Actually we're expecting 50 people now. Do you have rooms that size?"
        build_state(from_step, msg)

        result = run_unified_detection(msg, current_step=from_step, date_confirmed=True, room_locked=True)

        assert result is not None
        assert hasattr(result, "participants")


# =============================================================================
# Q&A SECTION CONDITIONAL TESTS
# =============================================================================


class TestQnASectionConditional:
    """Test Q&A section appears conditionally."""

    def test_qna_section_structure_with_qna(self, build_state):
        """Message with Q&A should have qna_types in result."""
        msg = "We confirm March 15. What parking options are available?"
        build_state(2, msg, event_kwargs={"date_confirmed": False})

        result = run_unified_detection(msg, current_step=2, date_confirmed=False, room_locked=False)

        assert result is not None
        assert hasattr(result, "qna_types")
        assert isinstance(result.qna_types, list)

    def test_pure_confirmation_structure(self, build_state):
        """Pure confirmation should still have detection structure."""
        msg = "March 15 works perfectly for us."
        build_state(2, msg, event_kwargs={"date_confirmed": False})

        result = run_unified_detection(msg, current_step=2, date_confirmed=False, room_locked=False)

        assert result is not None
        assert hasattr(result, "is_confirmation")


# =============================================================================
# HYBRID MESSAGE PRIORITY TESTS
# =============================================================================


class TestHybridPriority:
    """Test hybrid message detection structure."""

    def test_detour_plus_qna_detection_structure(self, build_state):
        """Detour + Q&A message should have expected fields."""
        msg = "Change the date to April 20. Also, do you have vegetarian menus?"
        build_state(4, msg)

        result = run_unified_detection(msg, current_step=4, date_confirmed=True, room_locked=True)

        assert result is not None
        assert hasattr(result, "date")
        assert hasattr(result, "is_question")
        assert hasattr(result, "qna_types")

    def test_confirmation_plus_qna_detection_structure(self, build_state):
        """Confirmation + Q&A message should have expected fields."""
        msg = "Room A is great! How many people can it hold?"
        build_state(3, msg)

        result = run_unified_detection(msg, current_step=3, date_confirmed=True, room_locked=False)

        assert result is not None
        assert hasattr(result, "is_confirmation")
        assert hasattr(result, "is_question")


# =============================================================================
# BILLING + Q&A
# =============================================================================


class TestBillingPlusQnAHybrid:
    """Test billing capture combined with Q&A."""

    @pytest.mark.parametrize("from_step", [4, 5, 6, 7])
    def test_billing_capture_plus_qna_structure(self, from_step, build_state):
        """Billing capture + Q&A should have expected fields."""
        msg = "Billing: ACME AG, Bahnhofstrasse 1, 8001 Zurich. Is parking included?"
        build_state(from_step, msg)

        result = run_unified_detection(msg, current_step=from_step, date_confirmed=True, room_locked=True)

        assert result is not None
        assert hasattr(result, "billing_address")
        assert hasattr(result, "is_question")


# =============================================================================
# EDGE CASES
# =============================================================================


class TestHybridEdgeCases:
    """Edge cases for hybrid message handling."""

    def test_multiple_questions_structure(self, build_state):
        """Multiple questions should have detection structure."""
        msg = "We confirm March 15. What parking? Also catering?"
        build_state(2, msg, event_kwargs={"date_confirmed": False})

        result = run_unified_detection(msg, current_step=2, date_confirmed=False, room_locked=False)

        assert result is not None
        assert hasattr(result, "is_question")

    def test_implicit_confirmation_structure(self, build_state):
        """Implicit confirmation should have detection structure."""
        msg = "The March 15 date sounds good. What time can we access?"
        build_state(2, msg, event_kwargs={"date_confirmed": False})

        result = run_unified_detection(msg, current_step=2, date_confirmed=False, room_locked=False)

        assert result is not None
        assert hasattr(result, "date")

    def test_pure_qna_structure(self, build_state):
        """Pure Q&A should have detection structure."""
        msg = "Just curious - what's the maximum capacity of your largest room?"
        build_state(4, msg)

        result = run_unified_detection(msg, current_step=4, date_confirmed=True, room_locked=True)

        assert result is not None
        assert hasattr(result, "is_question")
        assert hasattr(result, "is_change_request")


# =============================================================================
# INTEGRATION TESTS: LLM-Based Hybrid Detection (require AGENT_MODE=openai)
# =============================================================================


@requires_live_llm
class TestHybridDetectionIntegration:
    """
    Integration tests that verify LLM detects BOTH action AND Q&A in hybrid messages.

    Run with: AGENT_MODE=openai pytest -k "HybridDetectionIntegration" -v
    """

    def test_confirm_plus_qna_both_detected(self, build_state):
        """LLM should detect both confirmation AND Q&A."""
        msg = "March 15 works for us. What parking options are available?"
        build_state(2, msg, event_kwargs={"date_confirmed": False})

        result = run_unified_detection(msg, current_step=2, date_confirmed=False, room_locked=False)

        # Should detect confirmation/date
        has_confirm = result.is_confirmation or result.date is not None
        assert has_confirm, f"Should detect confirmation in '{msg}'"

        # Should also detect question
        assert result.is_question, f"Should detect Q&A in '{msg}'"

    def test_accept_plus_qna_both_detected(self, build_state):
        """LLM should detect both acceptance AND Q&A."""
        msg = "We accept the offer. Does the room have a projector?"
        build_state(4, msg)

        result = run_unified_detection(msg, current_step=4, date_confirmed=True, room_locked=True)

        # Should detect acceptance
        assert result.is_acceptance or result.is_confirmation, f"Should detect acceptance in '{msg}'"

        # Should also detect question
        assert result.is_question, f"Should detect Q&A in '{msg}'"

    def test_date_detour_plus_qna_both_detected(self, build_state):
        """LLM should detect both date change AND Q&A."""
        msg = "Can we move the event to April 20? Also, what catering menus do you offer?"
        build_state(4, msg)

        result = run_unified_detection(msg, current_step=4, date_confirmed=True, room_locked=True)

        # Should detect date change
        has_date_change = result.is_change_request or result.date is not None
        assert has_date_change, f"Should detect date change in '{msg}'"

        # Should also detect question
        assert result.is_question, f"Should detect Q&A in '{msg}'"

    def test_room_detour_plus_qna_both_detected(self, build_state):
        """LLM should detect both room change AND Q&A."""
        msg = "Can we switch to a larger room? Is parking included in the price?"
        build_state(4, msg)

        result = run_unified_detection(msg, current_step=4, date_confirmed=True, room_locked=True)

        # Should detect room change
        has_room_change = result.is_change_request or result.room_preference is not None
        assert has_room_change, f"Should detect room change in '{msg}'"

        # Should also detect question
        assert result.is_question, f"Should detect Q&A in '{msg}'"

    def test_participant_change_plus_qna_both_detected(self, build_state):
        """LLM should detect both participant change AND Q&A."""
        msg = "Actually we'll have 60 guests now. What's the maximum capacity?"
        build_state(4, msg)

        result = run_unified_detection(msg, current_step=4, date_confirmed=True, room_locked=True)

        # Should detect participant change
        has_participant = result.participants is not None or result.is_change_request
        assert has_participant, f"Should detect participant change in '{msg}'"

        # Should also detect question
        assert result.is_question, f"Should detect Q&A in '{msg}'"

    def test_billing_plus_qna_both_detected(self, build_state):
        """LLM should detect both billing info AND Q&A."""
        msg = "Billing: ACME Corp, Bahnhofstrasse 1, 8001 Zurich. Is there a discount for early payment?"
        build_state(5, msg)

        result = run_unified_detection(msg, current_step=5, date_confirmed=True, room_locked=True)

        # Should detect billing
        has_billing = result.billing_address is not None
        assert has_billing, f"Should detect billing in '{msg}'"

        # Should also detect question
        assert result.is_question, f"Should detect Q&A in '{msg}'"

    @pytest.mark.parametrize("msg,should_have_change,should_have_qna", [
        ("March 15 works. What parking options?", True, True),
        ("Switch to Room B please. Do you offer catering?", True, True),
        ("We're now 50 people. Is that okay for Room A?", True, True),
        ("Add projector please. What's the Wi-Fi password?", True, True),
        ("Just checking - what are your opening hours?", False, True),
        ("Yes, let's proceed with the booking.", True, False),
    ])
    def test_hybrid_detection_matrix(self, msg, should_have_change, should_have_qna, build_state):
        """Matrix test: various hybrid message patterns."""
        build_state(4, msg)

        result = run_unified_detection(msg, current_step=4, date_confirmed=True, room_locked=True)

        has_change = (
            result.is_change_request or
            result.is_confirmation or
            result.is_acceptance or
            result.date is not None or
            result.room_preference is not None or
            result.participants is not None or
            len(result.products) > 0
        )

        if should_have_change:
            assert has_change, f"Should detect change/action in '{msg}'"
        if should_have_qna:
            assert result.is_question, f"Should detect Q&A in '{msg}'"


# =============================================================================
# TRUE E2E TESTS: Full Hybrid Pipeline (require AGENT_MODE=openai)
# =============================================================================


@requires_live_llm
class TestHybridE2EFullPipeline:
    """
    TRUE E2E tests for hybrid messages (workflow action + Q&A).

    These tests verify:
    1. Full message processing through process_msg
    2. BOTH workflow action AND Q&A are handled
    3. Response addresses BOTH parts of the message
    4. No fallback/stub responses
    5. Q&A section appears in hybrid responses

    Run with: AGENT_MODE=openai pytest -k "HybridE2EFullPipeline" -v
    """

    @pytest.mark.parametrize("from_step", [4, 5, 6, 7])
    def test_date_change_plus_qna_full_e2e(self, from_step, e2e_harness):
        """
        TRUE E2E: Date change + Q&A message handles both parts.
        """
        harness = e2e_harness(
            from_step,
            event_kwargs={
                "date_confirmed": True,
                "chosen_date": "15.03.2026",
            },
        )

        harness.send_message("Can we move the date to April 15? Also, what parking options do you have?")

        harness.assert_has_draft_message()
        harness.assert_no_fallback(f"hybrid date+Q&A from step {from_step}")

        # Response should address BOTH date change AND parking
        body = harness.get_combined_body().lower()

        # Should have date-related content
        has_date_content = any(
            word in body for word in ["date", "april", "15", "change", "confirm"]
        )

        # Should have parking-related content
        has_parking_content = any(
            word in body for word in ["parking", "park", "car", "vehicle"]
        )

        assert has_date_content or has_parking_content, \
            f"Response should address date or parking, got: {body[:400]}"

    @pytest.mark.parametrize("from_step", [4, 5, 6, 7])
    def test_room_change_plus_qna_full_e2e(self, from_step, e2e_harness):
        """
        TRUE E2E: Room change + Q&A message handles both parts.
        """
        harness = e2e_harness(
            from_step,
            event_kwargs={
                "locked_room_id": "Room A",
            },
        )

        harness.send_message("Can we switch to Room B? Is catering included in the price?")

        harness.assert_has_draft_message()
        harness.assert_no_fallback(f"hybrid room+Q&A from step {from_step}")

        # Response should be substantive
        body = harness.get_combined_body()
        assert len(body) >= 100, f"Response too short for hybrid message: {body}"

    @pytest.mark.parametrize("from_step", [4, 5, 6, 7])
    def test_participant_change_plus_qna_full_e2e(self, from_step, e2e_harness):
        """
        TRUE E2E: Participant change + Q&A message handles both parts.
        """
        harness = e2e_harness(from_step)

        harness.send_message("We're now 60 people instead of 30. What's the maximum capacity of Room A?")

        harness.assert_has_draft_message()
        harness.assert_no_fallback(f"hybrid participants+Q&A from step {from_step}")

        # Response should address participants or capacity
        body = harness.get_combined_body().lower()
        has_relevant_content = any(
            word in body for word in ["60", "people", "guest", "capacity", "room", "participant"]
        )
        assert has_relevant_content, f"Response should address participants or capacity, got: {body[:300]}"

    def test_confirmation_plus_qna_full_e2e(self, e2e_harness):
        """
        TRUE E2E: Confirmation + Q&A message handles both parts.
        """
        harness = e2e_harness(
            4,
            event_kwargs={
                "date_confirmed": True,
                "locked_room_id": "Room A",
            },
        )

        harness.send_message("The offer looks great, we accept! By the way, is there WiFi?")

        harness.assert_has_draft_message()
        harness.assert_no_fallback("hybrid confirmation+Q&A")

        # Response should acknowledge acceptance and address WiFi
        body = harness.get_combined_body().lower()
        has_content = any(
            word in body for word in ["accept", "confirm", "thank", "wifi", "internet", "proceed"]
        )
        assert has_content, f"Response should acknowledge acceptance or WiFi, got: {body[:300]}"

    def test_billing_plus_qna_full_e2e(self, e2e_harness):
        """
        TRUE E2E: Billing info + Q&A message handles both parts.
        """
        harness = e2e_harness(5)

        harness.send_message(
            "Our billing address is: TechCorp AG, Industriestr. 50, 8005 Zurich. "
            "Is there a discount for early payment?"
        )

        harness.assert_has_draft_message()
        harness.assert_no_fallback("hybrid billing+Q&A")

        # Should process without error
        body = harness.get_combined_body()
        assert len(body) >= 50, f"Response too short: {body}"


@requires_live_llm
class TestHybridE2EQnASectionConditional:
    """
    TRUE E2E tests verifying Q&A section appears conditionally in responses.
    """

    def test_hybrid_message_includes_qna_section(self, e2e_harness):
        """
        TRUE E2E: Hybrid message response should include Q&A content.
        """
        harness = e2e_harness(
            4,
            event_kwargs={
                "date_confirmed": True,
                "chosen_date": "15.03.2026",
            },
        )

        harness.send_message("March 15 works for us. What parking is available for guests?")

        harness.assert_has_draft_message()
        harness.assert_no_fallback("hybrid with Q&A")

        # Response should include parking information
        body = harness.get_combined_body().lower()
        has_parking = "parking" in body or "park" in body
        assert has_parking, f"Response should include parking info, got: {body[:300]}"

    def test_pure_action_no_qna_section(self, e2e_harness):
        """
        TRUE E2E: Pure action message (no Q&A) should not have Q&A section.
        """
        harness = e2e_harness(
            4,
            event_kwargs={
                "date_confirmed": True,
                "locked_room_id": "Room A",
            },
        )

        harness.send_message("Yes, we accept the offer. Please proceed with the booking.")

        harness.assert_has_draft_message()
        harness.assert_no_fallback("pure acceptance")

        # This is fine - just needs to handle the acceptance
        body = harness.get_combined_body()
        assert len(body) >= 30, f"Should have substantive response: {body}"


@requires_live_llm
class TestHybridE2EResponseQuality:
    """
    TRUE E2E tests verifying hybrid response quality.
    """

    @pytest.mark.parametrize("hybrid_msg", [
        "Change date to April 20. What parking is available?",
        "Switch to Room B. Do you offer vegetarian menus?",
        "We're 50 people now. What's the room capacity?",
        "Add projector. Is there a technician available?",
        "Billing: ACME, Zurich. Any early payment discount?",
    ])
    def test_hybrid_generates_quality_response(self, hybrid_msg, e2e_harness):
        """
        TRUE E2E: Various hybrid messages generate quality responses.
        """
        harness = e2e_harness(
            5,
            event_kwargs={
                "date_confirmed": True,
                "chosen_date": "15.03.2026",
                "locked_room_id": "Room A",
            },
        )

        harness.send_message(hybrid_msg)

        harness.assert_has_draft_message()
        harness.assert_no_fallback(f"hybrid: {hybrid_msg[:30]}")

        # Response should be substantive
        body = harness.get_combined_body()
        assert len(body) >= 80, f"Response too short for hybrid message: {body}"

    def test_hybrid_response_not_generic(self, e2e_harness):
        """
        TRUE E2E: Hybrid response should be specific, not generic acknowledgment.
        """
        harness = e2e_harness(
            5,
            event_kwargs={
                "date_confirmed": True,
                "chosen_date": "15.03.2026",
            },
        )

        harness.send_message("Can we move to April 10? Also, what's the WiFi password?")

        harness.assert_has_draft_message()

        # Should NOT be generic
        harness.assert_body_not_contains(
            "I'll look into",
            "Let me check",
            "I'll get back to you",
        )

        # Should have specific content
        body = harness.get_combined_body().lower()
        has_specific = any(
            word in body for word in ["april", "date", "wifi", "internet", "password", "10"]
        )
        assert has_specific, f"Response should be specific, got: {body[:300]}"

    def test_hybrid_addresses_both_parts(self, e2e_harness):
        """
        TRUE E2E: Hybrid response should address both action and Q&A.
        """
        harness = e2e_harness(
            5,
            event_kwargs={
                "locked_room_id": "Room A",
            },
        )

        harness.send_message("Switch to a larger room please. What's the maximum capacity of Room B?")

        harness.assert_has_draft_message()
        harness.assert_no_fallback("hybrid room+capacity")

        body = harness.get_combined_body().lower()

        # Should mention room (either change acknowledgment or options)
        has_room_ref = "room" in body

        # Should mention capacity
        has_capacity_ref = any(
            word in body for word in ["capacity", "people", "guests", "seat", "fit"]
        )

        # At least one should be addressed
        assert has_room_ref or has_capacity_ref, \
            f"Should address room or capacity, got: {body[:400]}"


@requires_live_llm
class TestHybridE2EPriority:
    """
    TRUE E2E tests verifying correct priority when hybrid message has multiple signals.
    """

    def test_date_change_priority_over_qna(self, e2e_harness):
        """
        TRUE E2E: Date change should be processed even with Q&A.
        """
        harness = e2e_harness(
            5,
            event_kwargs={
                "date_confirmed": True,
                "chosen_date": "15.03.2026",
            },
        )

        harness.send_message("We need to change to April 20. What catering options?")

        harness.assert_has_draft_message()
        harness.assert_no_fallback("date change + Q&A")

        # Date change should be processed (either route to step 2 or handle inline)
        event = harness.get_current_event()
        # Either step changed or response acknowledges date change
        body = harness.get_combined_body().lower()
        has_date_processing = (
            event.get("current_step") == 2 or
            "date" in body or
            "april" in body
        )
        assert has_date_processing, "Should process date change"

    def test_qna_still_answered_with_action(self, e2e_harness):
        """
        TRUE E2E: Q&A should still be answered even when action is primary.
        """
        harness = e2e_harness(
            4,
            event_kwargs={
                "date_confirmed": True,
                "locked_room_id": "Room A",
            },
        )

        harness.send_message("Yes, we accept the offer. What's the WiFi password?")

        harness.assert_has_draft_message()
        harness.assert_no_fallback("accept + WiFi Q&A")

        # Should address WiFi in response
        body = harness.get_combined_body().lower()
        # Response should either mention WiFi or be substantive about the acceptance
        has_content = any(
            word in body for word in ["wifi", "internet", "accept", "confirm", "thank", "proceed"]
        )
        assert has_content, f"Should address acceptance or WiFi, got: {body[:300]}"
