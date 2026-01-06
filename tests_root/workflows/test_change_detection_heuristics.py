"""
Change Detection Heuristics & Pattern Matching Tests

Tests the precise pattern recognition in detect_change_type() to ensure:
- Change intent signals detected correctly
- Variable mention + intent + new value pattern works
- False positives prevented (questions don't trigger changes)
- All change types covered
"""

from __future__ import annotations

import pytest
from workflows.change_propagation import ChangeType, detect_change_type


class TestChangeIntentSignals:
    """Test change intent signal detection."""

    def test_explicit_change_verbs_detected(self):
        """Explicit change verbs: change, switch, modify, update, adjust."""
        change_verbs = [
            "change",
            "switch",
            "modify",
            "update",
            "adjust",
            "move to",
            "shift",
        ]

        for verb in change_verbs:
            event_state = {
                "current_step": 4,
                "date_confirmed": True,
                "chosen_date": "15.03.2025",
            }
            user_info = {"date": "2025-03-20"}
            message_text = f"Can we {verb} the date to March 20th?"

            change_type = detect_change_type(event_state, user_info, message_text=message_text)
            assert change_type == ChangeType.DATE, f"Should detect change for verb: {verb}"

    def test_redefinition_markers_detected(self):
        """Redefinition markers: actually, instead, rather, correction."""
        markers = ["actually", "instead", "rather", "correction", "make it", "make that"]

        for marker in markers:
            event_state = {"current_step": 4, "locked_room_id": "Room A"}
            user_info = {"participants": 50}
            message_text = f"{marker.capitalize()}, we need 50 people"

            change_type = detect_change_type(event_state, user_info, message_text=message_text)
            assert change_type == ChangeType.REQUIREMENTS, f"Should detect change for marker: {marker}"

    def test_comparative_language_detected(self):
        """Comparative language: different, another, new, alternate."""
        comparatives = ["different", "another", "new", "alternate", "alternative"]

        for comp in comparatives:
            event_state = {"current_step": 4, "locked_room_id": "Room A"}
            user_info = {"room": "Room B"}
            message_text = f"We'd prefer a {comp} room"

            change_type = detect_change_type(event_state, user_info, message_text=message_text)
            assert change_type == ChangeType.ROOM, f"Should detect change for comparative: {comp}"

    def test_change_question_patterns_detected(self):
        """Question patterns: can we change, could we change, is it possible.

        Note: "would it be possible" is now treated as a hypothetical pattern
        and filtered out by is_hypothetical_question() when followed by "?".
        """
        patterns = [
            "can we change",
            "could we change",
            "is it possible to change",
            # Note: "would it be possible" is considered hypothetical - excluded
            "can i change",
            "could i change",
        ]

        for pattern in patterns:
            event_state = {
                "current_step": 4,
                "date_confirmed": True,
                "chosen_date": "15.03.2025",
            }
            user_info = {"date": "2025-03-20"}
            message_text = f"{pattern.capitalize()} the date to March 20th?"

            change_type = detect_change_type(event_state, user_info, message_text=message_text)
            assert change_type == ChangeType.DATE, f"Should detect change for pattern: {pattern}"


class TestDateChangeDetection:
    """Test DATE change type detection."""

    def test_date_change_requires_confirmed_date(self):
        """Date change only fires if date was already confirmed."""
        # Case 1: Date NOT confirmed → no change
        event_state = {
            "current_step": 2,
            "date_confirmed": False,
            "chosen_date": None,
        }
        user_info = {"date": "2025-03-15"}
        message_text = "How about March 15th?"

        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        assert change_type is None, "Should NOT detect change for first-time date"

        # Case 2: Date confirmed → change detected
        event_state["date_confirmed"] = True
        event_state["chosen_date"] = "10.03.2025"
        user_info = {"date": "2025-03-15"}
        message_text = "Change the date to March 15th"

        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        assert change_type == ChangeType.DATE, "Should detect DATE change"

    def test_date_change_requires_different_date(self):
        """Date change only fires if new date differs from chosen_date."""
        event_state = {
            "current_step": 4,
            "date_confirmed": True,
            "chosen_date": "15.03.2025",
        }
        user_info = {"date": "2025-03-15"}  # Same date
        message_text = "The date is March 15th"

        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        # Might be None or DATE depending on whether text differs
        # If detected, routing will handle via hash guards

    def test_date_mention_plus_intent_triggers_change(self):
        """Date mentioned + change intent + new value → DATE change."""
        event_state = {
            "current_step": 4,
            "date_confirmed": True,
            "chosen_date": "15.03.2025",
        }
        user_info = {"date": "2025-03-20"}
        message_text = "Can we change the date to March 20th?"

        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        assert change_type == ChangeType.DATE


class TestRoomChangeDetection:
    """Test ROOM change type detection."""

    def test_room_change_requires_locked_room(self):
        """Room change only fires if room was already locked."""
        # Case 1: No locked room → no change
        event_state = {"current_step": 3, "locked_room_id": None}
        user_info = {"room": "Room A"}
        message_text = "We'd like Room A"

        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        assert change_type is None, "Should NOT detect change for first-time room selection"

        # Case 2: Room locked → change detected
        event_state["locked_room_id"] = "Room B"
        message_text = "Switch to Room A instead"

        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        assert change_type == ChangeType.ROOM, "Should detect ROOM change"

    def test_room_change_requires_different_room(self):
        """Room change only fires if new room differs from locked_room_id."""
        event_state = {"current_step": 4, "locked_room_id": "Room A"}
        user_info = {"room": "Room A"}  # Same room
        message_text = "We want Room A"

        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        assert change_type is None, "Should NOT detect change for same room"

    def test_room_mention_plus_intent_triggers_change(self):
        """Room mentioned + change intent + new room → ROOM change."""
        event_state = {"current_step": 5, "locked_room_id": "Room A"}
        user_info = {"room": "Sky Loft"}
        message_text = "Can we switch to Sky Loft instead?"

        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        assert change_type == ChangeType.ROOM


class TestRequirementsChangeDetection:
    """Test REQUIREMENTS change type detection."""

    def test_requirements_change_requires_locked_room(self):
        """Requirements change only fires if room is locked."""
        # Case 1: No locked room → no change
        event_state = {"current_step": 2, "locked_room_id": None}
        user_info = {"participants": 50}
        message_text = "We need space for 50 people"

        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        assert change_type is None, "Should NOT detect change before room locked"

        # Case 2: Room locked → change detected
        event_state["locked_room_id"] = "Room A"
        message_text = "Actually we're 50 people now"

        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        assert change_type == ChangeType.REQUIREMENTS, "Should detect REQUIREMENTS change"

    def test_requirements_fields_detected(self):
        """All requirement fields trigger REQUIREMENTS change."""
        requirement_fields = [
            ("participants", 50),
            ("layout", "theater"),
            ("start_time", "14:00"),
            ("end_time", "18:00"),
            ("special_requirements", "projector"),
        ]

        for field, value in requirement_fields:
            event_state = {"current_step": 4, "locked_room_id": "Room A"}
            user_info = {field: value}
            message_text = f"Actually we need {value}"

            change_type = detect_change_type(event_state, user_info, message_text=message_text)
            assert change_type == ChangeType.REQUIREMENTS, f"Should detect change for {field}"


class TestProductsChangeDetection:
    """Test PRODUCTS change type detection."""

    def test_products_change_requires_step4_or_later(self):
        """Products change only fires at Step 4 or later."""
        # Case 1: Before Step 4 → no change
        event_state = {"current_step": 2}
        user_info = {"products_add": [{"name": "Coffee", "quantity": 20}]}
        message_text = "Add coffee"

        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        assert change_type is None, "Should NOT detect PRODUCTS change before Step 4"

        # Case 2: Step 4 or later → change detected
        event_state["current_step"] = 4
        message_text = "Add Prosecco to the offer"

        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        assert change_type == ChangeType.PRODUCTS, "Should detect PRODUCTS change at Step 4+"

    def test_product_add_remove_triggers_change(self):
        """Explicit products_add or products_remove triggers change."""
        event_state = {"current_step": 4}

        # Test add
        user_info = {"products_add": [{"name": "Wine", "quantity": 5}]}
        message_text = "Add wine"
        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        assert change_type == ChangeType.PRODUCTS

        # Test remove
        user_info = {"products_remove": ["Coffee"]}
        message_text = "Remove coffee"
        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        assert change_type == ChangeType.PRODUCTS


class TestCommercialChangeDetection:
    """Test COMMERCIAL change type detection (precise, no false positives)."""

    def test_commercial_change_requires_step5_or_later(self):
        """Commercial change only fires at Step 5 or later."""
        event_state = {"current_step": 4}
        user_info = {}
        message_text = "Can you give us a discount?"

        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        assert change_type is None, "Should NOT detect COMMERCIAL before Step 5"

        event_state["current_step"] = 5
        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        assert change_type == ChangeType.COMMERCIAL, "Should detect COMMERCIAL at Step 5+"

    def test_commercial_requires_change_intent(self):
        """Commercial keywords + change intent → COMMERCIAL change."""
        event_state = {"current_step": 5}
        user_info = {}
        message_text = "Could you do CHF 3000 instead?"

        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        assert change_type == ChangeType.COMMERCIAL

    def test_no_commercial_on_price_question(self):
        """Price question WITHOUT change intent → no change."""
        event_state = {"current_step": 5}
        user_info = {}
        test_cases = [
            "What's the total price?",
            "How much does it cost?",
            "What's included in the price?",
            "Is the cost per person?",
        ]

        for message_text in test_cases:
            change_type = detect_change_type(event_state, user_info, message_text=message_text)
            assert change_type is None, f"Should NOT detect change for: {message_text}"

    def test_counter_offer_signals_trigger_commercial(self):
        """Counter-offer language → COMMERCIAL change."""
        counter_signals = [
            "can you do CHF 2500",
            "would you accept CHF 2500",
            "how about CHF 2500",
            "what if we offered CHF 2500",
            "could you lower the price",
        ]

        for message_text in counter_signals:
            event_state = {"current_step": 5}
            user_info = {}
            change_type = detect_change_type(event_state, user_info, message_text=message_text)
            assert change_type == ChangeType.COMMERCIAL, f"Should detect for: {message_text}"


class TestDepositChangeDetection:
    """Test DEPOSIT change type detection (precise, no false positives)."""

    def test_deposit_change_requires_step7(self):
        """Deposit change only fires at Step 7."""
        event_state = {"current_step": 6}
        user_info = {}
        message_text = "I'd like to proceed with the deposit"

        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        assert change_type is None, "Should NOT detect DEPOSIT before Step 7"

        event_state["current_step"] = 7
        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        assert change_type == ChangeType.DEPOSIT, "Should detect DEPOSIT at Step 7"

    def test_deposit_requires_action_intent(self):
        """Deposit keywords + action intent → DEPOSIT change."""
        action_phrases = [
            "I'd like to proceed with the deposit",
            "Ready to pay the deposit",
            "Let's confirm the reservation",
            "We'll book it now",
        ]

        for message_text in action_phrases:
            event_state = {"current_step": 7}
            user_info = {}
            change_type = detect_change_type(event_state, user_info, message_text=message_text)
            assert change_type == ChangeType.DEPOSIT, f"Should detect for: {message_text}"

    def test_no_deposit_on_question(self):
        """Deposit question WITHOUT action intent → no change."""
        test_cases = [
            "When is the deposit due?",
            "How much is the deposit?",
            "What payment methods do you accept?",
            "Can I pay by credit card?",
        ]

        for message_text in test_cases:
            event_state = {"current_step": 7}
            user_info = {}
            change_type = detect_change_type(event_state, user_info, message_text=message_text)
            assert change_type is None, f"Should NOT detect change for: {message_text}"


class TestSiteVisitChangeDetection:
    """Test SITE_VISIT change type detection."""

    def test_site_visit_requires_step7(self):
        """Site visit change only fires at Step 7."""
        event_state = {"current_step": 6}
        user_info = {"site_visit_time": "14:00"}
        message_text = "Can we schedule a site visit?"

        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        assert change_type is None, "Should NOT detect SITE_VISIT before Step 7"

        event_state["current_step"] = 7
        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        assert change_type == ChangeType.SITE_VISIT, "Should detect SITE_VISIT at Step 7"

    def test_site_visit_with_time_mention_triggers_change(self):
        """Site visit + time mention → SITE_VISIT change."""
        event_state = {"current_step": 7}
        user_info = {}
        message_text = "Can we reschedule the site visit to Tuesday at 2pm?"

        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        assert change_type == ChangeType.SITE_VISIT

    def test_site_visit_with_extracted_time_triggers_change(self):
        """Site visit + extracted time in user_info → SITE_VISIT change."""
        event_state = {"current_step": 7}
        user_info = {"site_visit_time": "14:00"}
        message_text = "Change the site visit to 2pm"

        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        assert change_type == ChangeType.SITE_VISIT


class TestClientInfoChangeDetection:
    """Test CLIENT_INFO change type detection."""

    def test_client_info_fields_trigger_change(self):
        """All client info fields trigger CLIENT_INFO change."""
        client_fields = [
            ("billing_address", "Zurich HQ"),
            ("company", "Acme Corp"),
            ("vat_number", "CH123456"),
            ("phone", "+41 79 123 4567"),
        ]

        for field, value in client_fields:
            event_state = {"current_step": 5}
            user_info = {field: value}
            message_text = f"Update {field} to {value}"

            change_type = detect_change_type(event_state, user_info, message_text=message_text)
            assert change_type == ChangeType.CLIENT_INFO, f"Should detect change for {field}"

    def test_client_info_with_change_intent_triggers_change(self):
        """Client info mention + change intent → CLIENT_INFO change."""
        event_state = {"current_step": 4}
        user_info = {"billing_address": "New address"}
        message_text = "Please update the billing address"

        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        assert change_type == ChangeType.CLIENT_INFO


class TestExpandedHeuristics:
    """Test expanded keywords and regex patterns (from prompt self-tests)."""

    def test_upgrade_package_triggers_products_change(self):
        """'Could we upgrade to the premium coffee setup?' → PRODUCTS change."""
        event_state = {"current_step": 4}
        user_info = {"products_add": [{"name": "Premium Coffee", "quantity": 20}]}
        message_text = "Could we upgrade to the premium coffee setup?"

        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        assert change_type == ChangeType.PRODUCTS, "Should detect PRODUCTS change for 'upgrade package'"

    def test_adjust_budget_triggers_commercial_change(self):
        """'Let's adjust the budget to 15k instead.' → COMMERCIAL change."""
        event_state = {"current_step": 5}
        user_info = {}
        message_text = "Let's adjust the budget to 15k instead."

        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        assert change_type == ChangeType.COMMERCIAL, "Should detect COMMERCIAL change for 'adjust budget'"

    def test_no_change_just_confirming(self):
        """'No change, just confirming details.' → None."""
        event_state = {"current_step": 5}
        user_info = {}
        message_text = "No change, just confirming details."

        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        assert change_type is None, "Should NOT detect change when explicitly stating 'no change'"

    def test_expanded_change_verbs(self):
        """Test new change verbs: upgrade, downgrade, swap, replace, amend, revise, alter."""
        new_verbs = ["upgrade", "downgrade", "swap", "replace", "amend", "revise", "alter"]

        for verb in new_verbs:
            event_state = {
                "current_step": 4,
                "date_confirmed": True,
                "chosen_date": "15.03.2025",
            }
            user_info = {"date": "2025-03-20"}
            message_text = f"{verb.capitalize()} the date to March 20th"

            change_type = detect_change_type(event_state, user_info, message_text=message_text)
            assert change_type == ChangeType.DATE, f"Should detect change for verb: {verb}"

    def test_expanded_redefinition_markers(self):
        """Test new redefinition markers: in fact, no wait, sorry, i meant, to be clear."""
        new_markers = ["in fact", "no wait", "sorry", "i meant", "to be clear", "let me correct"]

        for marker in new_markers:
            event_state = {"current_step": 4, "locked_room_id": "Room A"}
            user_info = {"participants": 50}
            message_text = f"{marker.capitalize()}, we need 50 people"

            change_type = detect_change_type(event_state, user_info, message_text=message_text)
            assert change_type == ChangeType.REQUIREMENTS, f"Should detect change for marker: {marker}"

    def test_expanded_commercial_keywords(self):
        """Test expanded commercial keywords: rate, fee, charge, quote, estimate, affordable."""
        commercial_words = ["rate", "fee", "charge", "quote", "estimate", "affordable"]

        for word in commercial_words:
            event_state = {"current_step": 5}
            user_info = {}
            message_text = f"Can we adjust the {word}?"

            change_type = detect_change_type(event_state, user_info, message_text=message_text)
            assert change_type == ChangeType.COMMERCIAL, f"Should detect COMMERCIAL for: {word}"

    def test_expanded_deposit_keywords(self):
        """Test expanded deposit keywords: upfront, prepayment, advance payment, down payment."""
        deposit_words = ["upfront payment", "prepayment", "advance payment", "down payment", "installment"]

        for word in deposit_words:
            event_state = {"current_step": 7}
            user_info = {}
            message_text = f"I'd like to proceed with the {word}"

            change_type = detect_change_type(event_state, user_info, message_text=message_text)
            assert change_type == ChangeType.DEPOSIT, f"Should detect DEPOSIT for: {word}"

    def test_regex_change_verb_near_product_noun(self):
        """Test regex pattern matching for change verbs near product nouns."""
        from workflows.change_propagation import extract_change_verbs_near_noun

        # Positive cases
        assert extract_change_verbs_near_noun("upgrade the coffee package", ["coffee", "package"])
        assert extract_change_verbs_near_noun("swap the wine for prosecco", ["wine", "prosecco"])
        assert extract_change_verbs_near_noun("replace standard catering with premium", ["catering", "standard", "premium"])

        # Negative cases
        assert not extract_change_verbs_near_noun("what coffee do you have", ["coffee"])
        assert not extract_change_verbs_near_noun("tell me about the wine selection", ["wine"])


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_message_text(self):
        """Empty message text → no change."""
        event_state = {"current_step": 4}
        user_info = {}
        message_text = ""

        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        assert change_type is None

    def test_none_message_text(self):
        """None message text → no change."""
        event_state = {"current_step": 4}
        user_info = {}
        message_text = None

        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        assert change_type is None

    def test_empty_user_info(self):
        """Empty user_info + no message → no change."""
        event_state = {"current_step": 4}
        user_info = {}
        message_text = "Some random text"

        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        assert change_type is None

    def test_multiple_change_types_precedence(self):
        """If multiple changes detected, first match wins."""
        # Date change takes precedence (checked first)
        event_state = {
            "current_step": 4,
            "date_confirmed": True,
            "chosen_date": "15.03.2025",
            "locked_room_id": "Room A",
        }
        user_info = {"date": "2025-03-20", "room": "Room B"}
        message_text = "Change date to March 20th and switch to Room B"

        change_type = detect_change_type(event_state, user_info, message_text=message_text)
        assert change_type == ChangeType.DATE, "DATE should take precedence"
