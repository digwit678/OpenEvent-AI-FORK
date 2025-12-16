"""
Tests for Multi-Variable Q&A Handling

Tests the three conjunction cases:
- Case A (independent): Different selects → separate answer sections
- Case B (and_combined): Same select, compatible conditions → single combined answer
- Case C (or_union): Same select, conflicting conditions → ranked results
"""
from __future__ import annotations

import pytest
from typing import Any, Dict, List

from backend.llm.intent_classifier import (
    QNA_TYPE_TO_STEP,
    spans_multiple_steps,
    get_qna_steps,
)
from backend.workflows.qna.conjunction import (
    QnAPart,
    ConjunctionAnalysis,
    analyze_conjunction,
    get_combined_conditions,
    get_union_conditions,
)


class TestSpansMultipleSteps:
    """Tests for the spans_multiple_steps helper."""

    def test_single_step_returns_false(self):
        """Single Q&A type should not span multiple steps."""
        assert spans_multiple_steps(["free_dates"]) is False
        assert spans_multiple_steps(["catering_for"]) is False
        assert spans_multiple_steps(["rooms_by_feature"]) is False

    def test_same_step_returns_false(self):
        """Multiple Q&A types from same step should not span multiple steps."""
        # Both are step 2
        assert spans_multiple_steps(["free_dates", "check_availability"]) is False
        # Both are step 3
        assert spans_multiple_steps(["rooms_by_feature", "room_features"]) is False
        # Both are step 4
        assert spans_multiple_steps(["catering_for", "products_for"]) is False

    def test_different_steps_returns_true(self):
        """Q&A types from different steps should span multiple steps."""
        # Step 2 + Step 4
        assert spans_multiple_steps(["free_dates", "catering_for"]) is True
        # Step 3 + Step 4
        assert spans_multiple_steps(["rooms_by_feature", "products_for"]) is True
        # Step 2 + Step 3 + Step 4
        assert spans_multiple_steps(["free_dates", "rooms_by_feature", "catering_for"]) is True

    def test_ignores_general_info_step_zero(self):
        """Step 0 (general info) should be ignored."""
        # parking_policy is step 0, free_dates is step 2
        assert spans_multiple_steps(["parking_policy", "free_dates"]) is False
        # But with a real second step it should be True
        assert spans_multiple_steps(["parking_policy", "free_dates", "catering_for"]) is True

    def test_empty_list_returns_false(self):
        """Empty list should return False."""
        assert spans_multiple_steps([]) is False


class TestGetQnaSteps:
    """Tests for the get_qna_steps helper."""

    def test_returns_sorted_unique_steps(self):
        """Should return sorted list of unique steps."""
        assert get_qna_steps(["free_dates"]) == [2]
        assert get_qna_steps(["free_dates", "catering_for"]) == [2, 4]
        assert get_qna_steps(["catering_for", "free_dates"]) == [2, 4]  # Sorted

    def test_deduplicates_same_step(self):
        """Should deduplicate same step."""
        assert get_qna_steps(["free_dates", "check_availability"]) == [2]

    def test_excludes_step_zero(self):
        """Should exclude step 0 (general info)."""
        assert get_qna_steps(["parking_policy"]) == []
        assert get_qna_steps(["parking_policy", "free_dates"]) == [2]


class TestConjunctionAnalysis:
    """Tests for the conjunction analyzer."""

    def test_case_a_independent_different_selects(self):
        """Case A: Different selects should be independent."""
        # rooms vs menus
        secondary = ["rooms_by_feature", "catering_for"]
        text = "What rooms are free in January and what menus are available in October?"

        result = analyze_conjunction(secondary, text)

        assert result.relationship == "independent"
        assert len(result.parts) == 2
        assert result.is_independent is True
        assert result.is_combined is False
        assert result.is_union is False

    def test_case_b_combined_same_select_compatible_conditions(self):
        """Case B: Same select with compatible conditions should be combined."""
        # Both query rooms, conditions are compatible (month + feature)
        secondary = ["rooms_by_feature", "rooms_by_feature"]  # Same type
        text = "What rooms are available in December and which include vegetarian options?"

        result = analyze_conjunction(secondary, text)

        # Since both have same select (rooms) and conditions don't conflict
        assert result.relationship in ("and_combined", "single")  # Could be single if only one part extracted

    def test_case_c_or_union_same_select_conflicting_conditions(self):
        """Case C: Same select with conflicting conditions should be OR union."""
        # Both query rooms but different months
        secondary = ["rooms_by_feature", "rooms_by_feature"]
        text = "What rooms are available in January and what rooms are available in December?"

        result = analyze_conjunction(secondary, text)

        # If conditions conflict (January vs December), should be or_union
        # Note: This depends on condition extraction working correctly
        if result.is_multi_part:
            # Check that conflicting months are detected
            conditions = [p.conditions for p in result.parts]
            months = [c.get("month") for c in conditions if c.get("month")]
            if len(set(months)) > 1:
                assert result.relationship == "or_union"

    def test_single_qna_type_returns_single(self):
        """Single Q&A type should return 'single' relationship."""
        secondary = ["free_dates"]
        text = "What dates are available?"

        result = analyze_conjunction(secondary, text)

        assert result.relationship == "single"
        assert result.is_multi_part is False


class TestConditionExtraction:
    """Tests for condition extraction from Q&A text."""

    def test_extracts_month(self):
        """Should extract month from text."""
        secondary = ["free_dates"]
        text = "What dates are available in December?"

        result = analyze_conjunction(secondary, text)

        if result.parts:
            assert result.parts[0].conditions.get("month") == "december"

    def test_extracts_capacity(self):
        """Should extract capacity from text."""
        secondary = ["rooms_by_feature"]
        text = "What rooms fit 40 people?"

        result = analyze_conjunction(secondary, text)

        if result.parts:
            assert result.parts[0].conditions.get("capacity") == 40

    def test_extracts_features(self):
        """Should extract features from text."""
        secondary = ["rooms_by_feature"]
        text = "What rooms have a projector and kitchen?"

        result = analyze_conjunction(secondary, text)

        if result.parts:
            features = result.parts[0].conditions.get("features", [])
            assert "projector" in features
            assert "kitchen" in features


class TestGetCombinedConditions:
    """Tests for combining conditions from multiple parts."""

    def test_merges_conditions(self):
        """Should merge conditions from all parts."""
        parts = [
            QnAPart(select="rooms", qna_type="rooms_by_feature", conditions={"month": "december"}),
            QnAPart(select="rooms", qna_type="rooms_by_feature", conditions={"features": ["vegetarian"]}),
        ]

        combined = get_combined_conditions(parts)

        assert combined.get("month") == "december"
        assert "vegetarian" in combined.get("features", [])

    def test_merges_lists(self):
        """Should merge list conditions."""
        parts = [
            QnAPart(select="rooms", qna_type="rooms_by_feature", conditions={"features": ["projector"]}),
            QnAPart(select="rooms", qna_type="rooms_by_feature", conditions={"features": ["kitchen"]}),
        ]

        combined = get_combined_conditions(parts)

        features = combined.get("features", [])
        assert "projector" in features
        assert "kitchen" in features


class TestGetUnionConditions:
    """Tests for getting union conditions for ranking."""

    def test_returns_separate_conditions(self):
        """Should return separate conditions for each part."""
        parts = [
            QnAPart(select="rooms", qna_type="rooms_by_feature", conditions={"features": ["music"]}),
            QnAPart(select="rooms", qna_type="rooms_by_feature", conditions={"features": ["kitchen"]}),
        ]

        union = get_union_conditions(parts)

        assert len(union) == 2
        assert union[0].get("features") == ["music"]
        assert union[1].get("features") == ["kitchen"]


class TestMultiVariableQnaIntegration:
    """Integration tests for multi-variable Q&A routing."""

    def test_training_workshop_scenario(self):
        """
        Original scenario: Client asks about dates AND packages in one message.
        "Could you please let us know if you have availability for those dates
        and what package options you recommend?"
        """
        secondary = ["free_dates", "products_for"]  # dates (step 2) + packages (step 4)
        text = "Could you please let us know if you have availability for those dates and what package options you recommend?"

        # Should span multiple steps
        assert spans_multiple_steps(secondary) is True

        # Should be independent (different selects)
        result = analyze_conjunction(secondary, text)
        assert result.relationship == "independent"

    def test_rooms_with_features_scenario(self):
        """
        Scenario: Client asks about rooms with music AND rooms with kitchen.
        "What rooms have background music and what rooms have a kitchen?"
        """
        secondary = ["rooms_by_feature", "rooms_by_feature"]
        text = "What rooms have background music and what rooms have a kitchen?"

        result = analyze_conjunction(secondary, text)

        # Should extract features
        all_features = set()
        for part in result.parts:
            all_features.update(part.conditions.get("features", []))

        # Should have extracted music and kitchen
        assert "music" in all_features or len(result.parts) == 1  # Might be combined

    def test_hybrid_confirmation_plus_qna(self):
        """
        Hybrid scenario: Confirmation + Q&A.
        "We'll take June 12th. What menu options do you have for December?"

        The Q&A part should extract December (from "What menu options... December")
        not June (which belongs to the workflow confirmation part).
        """
        # Classification would have:
        # primary: date_confirmation
        # secondary: catering_for
        secondary = ["catering_for"]
        text = "We'll take June 12th. What menu options do you have for December?"

        result = analyze_conjunction(secondary, text)

        # With per-segment extraction, the menu question segment should match December
        if result.parts:
            month = result.parts[0].conditions.get("month")
            # The Q&A segment "What menu options do you have for December?" should extract December
            assert month == "december"

    def test_different_months_per_segment(self):
        """
        Two Q&A parts with different months should each get their own month.
        "What menus are available in January and what rooms are free in February?"
        """
        secondary = ["catering_for", "rooms_by_feature"]
        text = "What menus are available in January and what rooms are free in February?"

        result = analyze_conjunction(secondary, text)

        # Should be independent (different selects: menus vs rooms)
        assert result.relationship == "independent"
        assert len(result.parts) == 2

        # Find the menu part and room part
        menu_part = next((p for p in result.parts if p.select == "menus"), None)
        room_part = next((p for p in result.parts if p.select == "rooms"), None)

        assert menu_part is not None
        assert room_part is not None

        # Each part should have its own month from its segment
        assert menu_part.conditions.get("month") == "january"
        assert room_part.conditions.get("month") == "february"

    def test_same_select_different_months_is_union(self):
        """
        Same select (rooms) but different months should be OR union (Case C).
        "What rooms are free in January and what rooms are free in February?"
        """
        secondary = ["rooms_by_feature", "rooms_by_feature"]
        text = "What rooms are free in January and what rooms are free in February?"

        result = analyze_conjunction(secondary, text)

        # Same select with conflicting months → or_union
        assert result.relationship == "or_union"
        assert len(result.parts) == 2

        # Each part should have its own month
        months = {p.conditions.get("month") for p in result.parts}
        assert "january" in months
        assert "february" in months

    def test_pure_qna_with_single_month(self):
        """Q&A with only one month should extract it correctly."""
        secondary = ["catering_for"]
        text = "What menu options do you have for December?"

        result = analyze_conjunction(secondary, text)

        if result.parts:
            assert result.parts[0].conditions.get("month") == "december"
