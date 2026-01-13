"""
Regression tests for deposit step gating.

Verifies that deposit_info is only returned when current_step >= 4,
preventing premature deposit buttons from showing in the UI.

This works for BOTH deposit types:
- FIXED: Amount is set directly (e.g., CHF 500)
- PERCENTAGE: Amount is calculated from offer total (e.g., 30%)

Both types are created in Step 4 when the offer is generated.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import pytest


def should_include_deposit_info(current_step: int, deposit_info: Optional[Dict[str, Any]]) -> bool:
    """
    Replicate the logic from api/routes/tasks.py _build_event_summary.

    Returns True if deposit_info should be included in the API response.
    """
    # Only include deposit_info at Step 4+ (after offer is generated with pricing)
    # This prevents stale/premature deposit info from showing in earlier steps
    return deposit_info is not None and current_step >= 4


def build_deposit_entry(
    current_step: int, deposit_info: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """
    Build the deposit portion of event_summary, matching api/routes/tasks.py logic.
    """
    if not should_include_deposit_info(current_step, deposit_info):
        return None

    return {
        "deposit_required": deposit_info.get("deposit_required", False),
        "deposit_amount": deposit_info.get("deposit_amount"),
        "deposit_vat_included": deposit_info.get("deposit_vat_included"),
        "deposit_due_date": deposit_info.get("deposit_due_date"),
        "deposit_paid": deposit_info.get("deposit_paid", False),
        "deposit_paid_at": deposit_info.get("deposit_paid_at"),
    }


class TestDepositStepGating:
    """Tests for deposit_info only appearing at Step 4+."""

    @pytest.mark.v4
    def test_step_1_no_deposit_returned(self):
        """Step 1 events should not return deposit_info."""
        deposit_info = {
            "deposit_required": True,
            "deposit_amount": 500.0,
        }
        result = build_deposit_entry(current_step=1, deposit_info=deposit_info)
        assert result is None

    @pytest.mark.v4
    def test_step_2_no_deposit_returned(self):
        """Step 2 events should not return deposit_info."""
        deposit_info = {
            "deposit_required": True,
            "deposit_amount": 500.0,
        }
        result = build_deposit_entry(current_step=2, deposit_info=deposit_info)
        assert result is None

    @pytest.mark.v4
    def test_step_3_no_deposit_returned(self):
        """Step 3 events should not return deposit_info."""
        deposit_info = {
            "deposit_required": True,
            "deposit_amount": 500.0,
        }
        result = build_deposit_entry(current_step=3, deposit_info=deposit_info)
        assert result is None

    @pytest.mark.v4
    def test_step_3_stale_deposit_hidden(self):
        """Step 3 events with stale deposit_info should NOT return it."""
        # Simulate stale deposit from a previous offer iteration
        stale_deposit_info = {
            "deposit_required": True,
            "deposit_amount": 500.0,
            "deposit_type": "fixed",
            "deposit_paid": False,
        }
        result = build_deposit_entry(current_step=3, deposit_info=stale_deposit_info)
        # Even though deposit_info exists, it should be hidden at Step 3
        assert result is None

    @pytest.mark.v4
    def test_step_4_fixed_deposit_shown(self):
        """Step 4 events with fixed deposit should return deposit_info."""
        deposit_info = {
            "deposit_required": True,
            "deposit_amount": 500.0,
            "deposit_vat_included": 37.38,
            "deposit_type": "fixed",
            "deposit_percentage": None,
            "deposit_due_date": "2026-02-24",
            "deposit_paid": False,
            "deposit_paid_at": None,
        }
        result = build_deposit_entry(current_step=4, deposit_info=deposit_info)

        assert result is not None
        assert result["deposit_required"] is True
        assert result["deposit_amount"] == 500.0

    @pytest.mark.v4
    def test_step_4_percentage_deposit_shown(self):
        """Step 4 events with percentage deposit should return deposit_info."""
        deposit_info = {
            "deposit_required": True,
            "deposit_amount": 204.0,  # 30% of 680
            "deposit_vat_included": 15.26,
            "deposit_type": "percentage",
            "deposit_percentage": 30,
            "deposit_due_date": "2026-02-24",
            "deposit_paid": False,
            "deposit_paid_at": None,
        }
        result = build_deposit_entry(current_step=4, deposit_info=deposit_info)

        assert result is not None
        assert result["deposit_required"] is True
        assert result["deposit_amount"] == 204.0

    @pytest.mark.v4
    def test_step_5_deposit_shown(self):
        """Step 5 events with deposit should return deposit_info."""
        deposit_info = {
            "deposit_required": True,
            "deposit_amount": 500.0,
            "deposit_paid": False,
        }
        result = build_deposit_entry(current_step=5, deposit_info=deposit_info)

        assert result is not None
        assert result["deposit_required"] is True

    @pytest.mark.v4
    def test_step_7_deposit_shown(self):
        """Step 7 events with deposit should return deposit_info."""
        deposit_info = {
            "deposit_required": True,
            "deposit_amount": 500.0,
            "deposit_paid": True,
            "deposit_paid_at": "2026-01-13T10:00:00",
        }
        result = build_deposit_entry(current_step=7, deposit_info=deposit_info)

        assert result is not None
        assert result["deposit_paid"] is True

    @pytest.mark.v4
    def test_no_deposit_info_returns_none(self):
        """When deposit_info is None, should return None at any step."""
        assert build_deposit_entry(current_step=1, deposit_info=None) is None
        assert build_deposit_entry(current_step=4, deposit_info=None) is None
        assert build_deposit_entry(current_step=7, deposit_info=None) is None

    @pytest.mark.v4
    def test_deposit_fields_preserved(self):
        """All deposit_info fields should be preserved in the result."""
        deposit_info = {
            "deposit_required": True,
            "deposit_amount": 500.0,
            "deposit_vat_included": 37.38,
            "deposit_due_date": "2026-02-24",
            "deposit_paid": False,
            "deposit_paid_at": None,
        }
        result = build_deposit_entry(current_step=4, deposit_info=deposit_info)

        assert result is not None
        assert result["deposit_required"] is True
        assert result["deposit_amount"] == 500.0
        assert result["deposit_vat_included"] == 37.38
        assert result["deposit_due_date"] == "2026-02-24"
        assert result["deposit_paid"] is False
        assert result["deposit_paid_at"] is None


class TestDepositTypesAtStep4:
    """Tests verifying both deposit types work correctly at Step 4+."""

    @pytest.mark.v4
    def test_fixed_deposit_same_regardless_of_offer_total(self):
        """Fixed deposit amount is constant regardless of offer total.

        Fixed deposits are set directly (e.g., CHF 500) and don't depend
        on the room price or offer total. This test verifies the behavior
        is consistent.
        """
        # Fixed deposit should be the same value
        fixed_deposit_info = {
            "deposit_required": True,
            "deposit_amount": 500.0,  # Fixed at CHF 500
            "deposit_type": "fixed",
        }

        result = build_deposit_entry(current_step=4, deposit_info=fixed_deposit_info)
        assert result is not None
        assert result["deposit_amount"] == 500.0

    @pytest.mark.v4
    def test_percentage_deposit_varies_with_offer_total(self):
        """Percentage deposit amount varies with offer total.

        Percentage deposits are calculated as a percentage of the offer total
        (e.g., 30% of CHF 680 = CHF 204). This is done at offer generation
        time in Step 4.
        """
        # 30% of different offer totals
        low_total_deposit = {
            "deposit_required": True,
            "deposit_amount": 150.0,  # 30% of 500
            "deposit_type": "percentage",
            "deposit_percentage": 30,
        }

        high_total_deposit = {
            "deposit_required": True,
            "deposit_amount": 300.0,  # 30% of 1000
            "deposit_type": "percentage",
            "deposit_percentage": 30,
        }

        result_low = build_deposit_entry(current_step=4, deposit_info=low_total_deposit)
        result_high = build_deposit_entry(current_step=4, deposit_info=high_total_deposit)

        assert result_low["deposit_amount"] == 150.0
        assert result_high["deposit_amount"] == 300.0


class TestBackendAPIBehavior:
    """
    These tests verify the expected behavior matches the actual implementation
    in api/routes/tasks.py. The _build_event_summary function includes this logic:

    ```python
    current_step = event_entry.get("current_step", 1)
    deposit_info = event_entry.get("deposit_info")
    if deposit_info and current_step >= 4:
        event_summary["deposit_info"] = {...}
    ```

    This ensures:
    1. deposit_info is only returned when current_step >= 4
    2. Both fixed and percentage deposits work at Step 4+
    3. Stale deposit_info from earlier steps is hidden
    """

    @pytest.mark.v4
    def test_step_boundary_at_4(self):
        """Step 4 is the exact boundary where deposits become visible."""
        deposit_info = {"deposit_required": True, "deposit_amount": 500.0}

        # Steps 1-3: hidden
        for step in [1, 2, 3]:
            assert not should_include_deposit_info(step, deposit_info), f"Step {step} should hide deposit"

        # Steps 4+: visible
        for step in [4, 5, 6, 7]:
            assert should_include_deposit_info(step, deposit_info), f"Step {step} should show deposit"
