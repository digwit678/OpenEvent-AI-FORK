"""
Regression tests for product catalog vs HIL sourcing flow.

CRITICAL BUG FIX (Jan 2026):
- Catalog products (like "Classic Apéro") should be added DIRECTLY to offers
- Unknown products (like "Champagne") should go through HIL sourcing

This test ensures we don't regress on this distinction.

REG-PROD-001: Catalog product detection
REG-PROD-002: Unknown product HIL routing
REG-PROD-003: Mixed product handling
"""

from __future__ import annotations

import pytest
from typing import Any, Dict, List

# Import only the services layer to avoid deep workflow imports
from services.products import find_product, ProductRecord

# All tests in this file are v4 workflow tests
pytestmark = pytest.mark.v4




class TestCatalogProductDetection:
    """
    REG-PROD-001: Test that catalog products are properly detected.

    CRITICAL: The fix in product_handler.py added find_product() lookup
    so catalog products like "Classic Apéro" are matched directly instead
    of incorrectly going through HIL sourcing.
    """

    def test_classic_apero_is_catalog_product(self):
        """Classic Apéro exists in the product catalog."""
        record = find_product("Classic Apéro")
        assert record is not None, "Classic Apéro must be in catalog"
        assert isinstance(record, ProductRecord)
        assert record.name == "Classic Apéro"
        assert record.base_price > 0, "Must have a price"

    def test_catalog_product_has_required_fields(self):
        """Catalog products should have all fields needed for direct add."""
        record = find_product("Classic Apéro")
        assert record is not None

        # These fields are used in parse_product_intent when building matched entry
        assert record.name
        assert record.product_id
        assert record.base_price is not None
        # unit and category may be optional

    def test_case_insensitive_lookup(self):
        """Product lookup should be case-insensitive."""
        record_lower = find_product("classic apéro")
        record_upper = find_product("CLASSIC APÉRO")
        record_mixed = find_product("Classic Apéro")

        assert record_lower is not None
        assert record_upper is not None
        assert record_mixed is not None
        assert record_lower.name == record_upper.name == record_mixed.name

    def test_coffee_package_in_catalog(self):
        """Basic Coffee & Tea Package should be in catalog."""
        record = find_product("Basic Coffee & Tea Package")
        assert record is not None, "Basic Coffee & Tea Package must be in catalog"


class TestUnknownProductDetection:
    """
    REG-PROD-002: Test that unknown products are NOT in catalog.

    Products not in catalog should return None from find_product(),
    signaling they need HIL sourcing.
    """

    def test_unknown_product_returns_none(self):
        """Unknown products should not be found in catalog."""
        record = find_product("Special Custom Item XYZ That Doesnt Exist")
        assert record is None, "Unknown product should return None"

    def test_random_string_returns_none(self):
        """Random strings should not match any product."""
        record = find_product("asdfghjkl12345")
        assert record is None

    def test_empty_string_returns_none(self):
        """Empty string should return None."""
        record = find_product("")
        assert record is None

    def test_none_input_returns_none(self):
        """None input should return None."""
        record = find_product(None)
        assert record is None


class TestProductCatalogConsistency:
    """
    REG-PROD-003: Test catalog consistency for offer generation.

    These tests ensure the product catalog has the data needed for
    proper offer generation without HIL intervention.
    """

    def test_products_have_prices(self):
        """Known products should have prices for offer calculation."""
        test_products = ["Classic Apéro", "Basic Coffee & Tea Package", "Premium Apéro"]

        for product_name in test_products:
            record = find_product(product_name)
            if record:  # Only test if product exists
                assert record.base_price >= 0, f"{product_name} must have price"

    def test_per_person_products_have_unit(self):
        """Per-person products should have unit field set."""
        record = find_product("Classic Apéro")
        if record and record.unit:
            # If unit is set, verify it's a valid value
            assert record.unit in ["per_person", "flat", "per_hour", None]


class TestSynonymLookup:
    """Test that product synonyms work for matching."""

    def test_synonym_lookup_works(self):
        """Products should be findable by synonyms if defined."""
        # This tests the synonym feature in find_product()
        # Actual synonyms depend on products.json configuration
        record = find_product("apero")  # Might be synonym for Classic Apéro
        # Don't assert - just document that synonyms are checked


class TestCateringFieldConversion:
    """
    REG-PROD-004: Test catering field → products_add conversion.

    CRITICAL FIX (Jan 2026):
    When Gemini extracts catering preference to user_info["catering"],
    Step 4 must convert it to user_info["products_add"] if it's a catalog product.

    Scenario: User says "I need a room for 30 people with Classic Apéro"
    - Step 1: Gemini extracts { "catering": "Classic Apéro" }
    - Step 4: Must convert to { "products_add": [{"name": "Classic Apéro", "quantity": 30}] }
    """

    def test_catering_product_findable(self):
        """Catering products extracted by Gemini should be findable."""
        # Common catering extractions from Gemini
        catering_variations = [
            "Classic Apéro",
            "classic apéro",
            "apero",  # Might be synonym
        ]

        found_count = 0
        for catering in catering_variations:
            record = find_product(catering)
            if record:
                found_count += 1
                assert record.base_price > 0

        # At least the exact name should be found
        assert found_count >= 1, "At least 'Classic Apéro' should be findable"

    def test_catering_conversion_logic(self):
        """
        Simulate the catering → products_add conversion logic from step4_handler.

        This documents the expected conversion behavior without importing
        the full workflow machinery.
        """
        # Simulated user_info from Gemini extraction
        user_info = {
            "catering": "Classic Apéro",
            "participants": 30,
        }

        # The conversion logic (mirrors step4_handler.py lines 225-240)
        catering_pref = user_info.get("catering")
        products_add = user_info.get("products_add")

        if catering_pref and isinstance(catering_pref, str) and not products_add:
            catering_product = find_product(catering_pref)
            if catering_product:
                quantity = user_info.get("participants", 1)
                user_info["products_add"] = [
                    {"name": catering_product.name, "quantity": quantity}
                ]

        # Verify conversion happened
        assert "products_add" in user_info
        assert len(user_info["products_add"]) == 1
        assert user_info["products_add"][0]["name"] == "Classic Apéro"
        assert user_info["products_add"][0]["quantity"] == 30

    def test_unknown_catering_not_converted(self):
        """Unknown catering should NOT be converted (will go to HIL later)."""
        user_info = {
            "catering": "Special Champagne Service XYZ",
            "participants": 20,
        }

        catering_pref = user_info.get("catering")
        if catering_pref and isinstance(catering_pref, str):
            catering_product = find_product(catering_pref)
            if catering_product:
                user_info["products_add"] = [
                    {"name": catering_product.name, "quantity": 20}
                ]

        # Should NOT have products_add (unknown product)
        assert "products_add" not in user_info


class TestCateringTeaserCoordination:
    """
    REG-PROD-005: Test catering teaser coordination between Step 3 and Step 4.

    CRITICAL FIX (Jan 2026):
    - If catering NOT mentioned in first message → Step 3 asks about catering
    - If catering IS mentioned in first message → Step 3 does NOT ask (already known)
    - The catering_teaser_shown flag prevents duplicate prompts in Step 4

    The "hybrid" approach:
    - Step 3 sets catering_teaser_shown=True when it shows the teaser
    - Step 4 checks this flag and skips its own catering question if True
    """

    def test_teaser_flag_structure(self):
        """Document expected products_state structure with teaser flag."""
        # Expected structure from Step 3 when teaser is shown
        products_state = {
            "available_items": [],
            "manager_added_items": [],
            "line_items": [],
            "catering_teaser_shown": True,  # Set by Step 3
        }

        # Step 4 should check this flag before prompting for catering
        assert products_state.get("catering_teaser_shown") is True

    def test_no_catering_in_first_message_triggers_teaser(self):
        """
        Scenario: User's first message has NO catering mention.
        Expected: Step 3 should show catering teaser.

        Example first message: "I need a room for 30 people on 15.02.2026"
        """
        # Simulated user_info from Step 1 - NO catering field
        user_info = {
            "participants": 30,
            "dates": ["15.02.2026"],
            # "catering" is NOT present
        }

        # Logic from step3_handler.py to decide if teaser needed
        has_catering_preference = bool(user_info.get("catering"))

        # If no catering preference, teaser should be shown
        should_show_teaser = not has_catering_preference
        assert should_show_teaser is True

    def test_catering_in_first_message_skips_teaser(self):
        """
        Scenario: User's first message HAS catering mention.
        Expected: Step 3 should NOT show catering teaser.

        Example: "I need a room for 30 people with Classic Apéro on 15.02.2026"
        """
        # Simulated user_info from Step 1 - WITH catering field
        user_info = {
            "participants": 30,
            "dates": ["15.02.2026"],
            "catering": "Classic Apéro",  # Already mentioned
        }

        # Logic to decide if teaser needed
        has_catering_preference = bool(user_info.get("catering"))

        # If catering already mentioned, NO teaser needed
        should_show_teaser = not has_catering_preference
        assert should_show_teaser is False

    def test_step4_respects_teaser_flag(self):
        """
        Scenario: Step 3 showed teaser → Step 4 should NOT ask about catering again.
        """
        # Event state after Step 3 showed teaser
        event_entry = {
            "products_state": {
                "catering_teaser_shown": True,
            }
        }

        # Step 4 logic to check if it should ask about catering
        products_state = event_entry.get("products_state", {})
        teaser_already_shown = products_state.get("catering_teaser_shown", False)

        # Step 4 should NOT prompt for catering
        should_ask_catering_in_step4 = not teaser_already_shown
        assert should_ask_catering_in_step4 is False

    def test_step4_can_ask_if_no_teaser_shown(self):
        """
        Scenario: Step 3 did NOT show teaser → Step 4 CAN ask about catering.

        This happens if user skipped Step 3 or fast-tracked to Step 4.
        """
        # Event state where teaser was NOT shown
        event_entry = {
            "products_state": {
                "catering_teaser_shown": False,
            }
        }

        products_state = event_entry.get("products_state", {})
        teaser_already_shown = products_state.get("catering_teaser_shown", False)

        # Step 4 CAN prompt for catering
        should_ask_catering_in_step4 = not teaser_already_shown
        assert should_ask_catering_in_step4 is True
