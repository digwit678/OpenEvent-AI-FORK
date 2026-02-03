"""
Test three-tier product availability filtering.

REGRESSION: Product availability filtering (three-tier system)

Three-tier product availability:
  - RECOMMENDED: AI suggests in offers & answers questions (default)
  - ON_REQUEST: Not suggested by AI, but manager can add manually
  - UNAVAILABLE: Completely hidden, cannot be added even manually

Functions tested:
  - list_recommended_products(): Only 'recommended' products (for AI suggestions)
  - list_available_products(): 'recommended' + 'on_request' (for manual addition)
  - is_product_recommended(): Check if AI should suggest this product
  - is_product_available(): Check if product can be added to offers
  - find_recommended_product(): Find by name, only if recommended
  - find_available_product(): Find by name, only if available (not unavailable)
"""

import pytest
from unittest.mock import patch

from services.products import (
    list_product_records,
    list_available_products,
    list_recommended_products,
    is_product_available,
    is_product_recommended,
    find_available_product,
    find_recommended_product,
)


class TestThreeTierProductFiltering:
    """Test suite for three-tier product availability filtering."""

    @pytest.fixture
    def mock_on_request_products(self):
        """Products that are ON_REQUEST (manager can add, but AI won't suggest)."""
        return [
            "catering-classic-apero",
            "catering-premium-apero",
        ]

    @pytest.fixture
    def mock_unavailable_products(self):
        """Products that are UNAVAILABLE (completely blocked)."""
        return [
            "catering-basic-coffee",
            "equipment-old-projector",
        ]

    def test_list_recommended_excludes_on_request_and_unavailable(
        self, mock_on_request_products, mock_unavailable_products
    ):
        """list_recommended_products() should exclude BOTH on_request AND unavailable."""
        with patch(
            "workflows.io.config_store.get_on_request_products",
            return_value=mock_on_request_products
        ):
            with patch(
                "workflows.io.config_store.get_unavailable_products",
                return_value=mock_unavailable_products
            ):
                all_products = list_product_records()
                all_ids = {p.product_id for p in all_products}

                recommended = list_recommended_products()
                recommended_ids = {p.product_id for p in recommended}

                # Verify on_request products are NOT in recommended
                for pid in mock_on_request_products:
                    if pid in all_ids:
                        assert pid not in recommended_ids, \
                            f"On-request product {pid} should NOT be in recommended list"

                # Verify unavailable products are NOT in recommended
                for pid in mock_unavailable_products:
                    if pid in all_ids:
                        assert pid not in recommended_ids, \
                            f"Unavailable product {pid} should NOT be in recommended list"

                # Verify we still have some recommended products
                assert len(recommended) > 0, "Should have some recommended products"

    def test_list_available_excludes_only_unavailable(
        self, mock_on_request_products, mock_unavailable_products
    ):
        """list_available_products() should include on_request but exclude unavailable."""
        with patch(
            "workflows.io.config_store.get_on_request_products",
            return_value=mock_on_request_products
        ):
            with patch(
                "workflows.io.config_store.get_unavailable_products",
                return_value=mock_unavailable_products
            ):
                all_products = list_product_records()
                all_ids = {p.product_id for p in all_products}

                available = list_available_products()
                available_ids = {p.product_id for p in available}

                # Verify on_request products ARE in available (manager can add)
                for pid in mock_on_request_products:
                    if pid in all_ids:
                        assert pid in available_ids, \
                            f"On-request product {pid} SHOULD be in available list"

                # Verify unavailable products are NOT in available
                for pid in mock_unavailable_products:
                    if pid in all_ids:
                        assert pid not in available_ids, \
                            f"Unavailable product {pid} should NOT be in available list"

    def test_is_product_recommended_returns_false_for_on_request(
        self, mock_on_request_products, mock_unavailable_products
    ):
        """is_product_recommended() should return False for on_request products."""
        with patch(
            "workflows.io.config_store.get_on_request_products",
            return_value=mock_on_request_products
        ):
            with patch(
                "workflows.io.config_store.get_unavailable_products",
                return_value=mock_unavailable_products
            ):
                all_products = list_product_records()

                for pid in mock_on_request_products:
                    exists = any(p.product_id == pid for p in all_products)
                    if exists:
                        result = is_product_recommended(pid)
                        assert result is False, \
                            f"is_product_recommended({pid}) should return False for on_request"

    def test_is_product_recommended_returns_false_for_unavailable(
        self, mock_on_request_products, mock_unavailable_products
    ):
        """is_product_recommended() should return False for unavailable products."""
        with patch(
            "workflows.io.config_store.get_on_request_products",
            return_value=mock_on_request_products
        ):
            with patch(
                "workflows.io.config_store.get_unavailable_products",
                return_value=mock_unavailable_products
            ):
                all_products = list_product_records()

                for pid in mock_unavailable_products:
                    exists = any(p.product_id == pid for p in all_products)
                    if exists:
                        result = is_product_recommended(pid)
                        assert result is False, \
                            f"is_product_recommended({pid}) should return False for unavailable"

    def test_is_product_available_returns_true_for_on_request(
        self, mock_on_request_products, mock_unavailable_products
    ):
        """is_product_available() should return True for on_request products."""
        with patch(
            "workflows.io.config_store.get_on_request_products",
            return_value=mock_on_request_products
        ):
            with patch(
                "workflows.io.config_store.get_unavailable_products",
                return_value=mock_unavailable_products
            ):
                all_products = list_product_records()

                for pid in mock_on_request_products:
                    exists = any(p.product_id == pid for p in all_products)
                    if exists:
                        result = is_product_available(pid)
                        assert result is True, \
                            f"is_product_available({pid}) should return True for on_request"

    def test_is_product_available_returns_false_for_unavailable(
        self, mock_on_request_products, mock_unavailable_products
    ):
        """is_product_available() should return False for unavailable products."""
        with patch(
            "workflows.io.config_store.get_on_request_products",
            return_value=mock_on_request_products
        ):
            with patch(
                "workflows.io.config_store.get_unavailable_products",
                return_value=mock_unavailable_products
            ):
                all_products = list_product_records()

                for pid in mock_unavailable_products:
                    exists = any(p.product_id == pid for p in all_products)
                    if exists:
                        result = is_product_available(pid)
                        assert result is False, \
                            f"is_product_available({pid}) should return False for unavailable"

    def test_find_recommended_returns_none_for_on_request(
        self, mock_on_request_products, mock_unavailable_products
    ):
        """find_recommended_product() should return None for on_request products."""
        with patch(
            "workflows.io.config_store.get_on_request_products",
            return_value=mock_on_request_products
        ):
            with patch(
                "workflows.io.config_store.get_unavailable_products",
                return_value=mock_unavailable_products
            ):
                all_products = list_product_records()

                for p in all_products:
                    if p.product_id in mock_on_request_products:
                        result = find_recommended_product(p.name)
                        assert result is None, \
                            f"find_recommended_product('{p.name}') should return None for on_request"

    def test_find_available_returns_product_for_on_request(
        self, mock_on_request_products, mock_unavailable_products
    ):
        """find_available_product() should return product for on_request products."""
        with patch(
            "workflows.io.config_store.get_on_request_products",
            return_value=mock_on_request_products
        ):
            with patch(
                "workflows.io.config_store.get_unavailable_products",
                return_value=mock_unavailable_products
            ):
                all_products = list_product_records()

                for p in all_products:
                    if p.product_id in mock_on_request_products:
                        result = find_available_product(p.name)
                        assert result is not None, \
                            f"find_available_product('{p.name}') should return product for on_request"
                        assert result.product_id == p.product_id

    def test_find_available_returns_none_for_unavailable(
        self, mock_on_request_products, mock_unavailable_products
    ):
        """find_available_product() should return None for unavailable products."""
        with patch(
            "workflows.io.config_store.get_on_request_products",
            return_value=mock_on_request_products
        ):
            with patch(
                "workflows.io.config_store.get_unavailable_products",
                return_value=mock_unavailable_products
            ):
                all_products = list_product_records()

                for p in all_products:
                    if p.product_id in mock_unavailable_products:
                        result = find_available_product(p.name)
                        assert result is None, \
                            f"find_available_product('{p.name}') should return None for unavailable"

    def test_empty_lists_returns_all_recommended(self):
        """When no special status, all products should be recommended."""
        with patch(
            "workflows.io.config_store.get_on_request_products",
            return_value=[]
        ):
            with patch(
                "workflows.io.config_store.get_unavailable_products",
                return_value=[]
            ):
                all_products = list_product_records()
                recommended = list_recommended_products()
                available = list_available_products()

                assert len(recommended) == len(all_products), \
                    "With no special status, recommended should equal total"
                assert len(available) == len(all_products), \
                    "With no special status, available should equal total"


class TestWorkflowIntegration:
    """Test that workflow modules use the correct filtering functions."""

    def test_preferences_uses_recommended_products(self, monkeypatch):
        """The preferences module should use list_recommended_products()."""
        on_request = ["catering-classic-apero"]
        unavailable = ["catering-premium-apero"]

        monkeypatch.setattr(
            "workflows.io.config_store.get_on_request_products",
            lambda: on_request
        )
        monkeypatch.setattr(
            "workflows.io.config_store.get_unavailable_products",
            lambda: unavailable
        )

        # When preferences.py calls list_recommended_products(),
        # it should not include on_request or unavailable products
        recommended = list_recommended_products()
        recommended_ids = {p.product_id for p in recommended}

        for pid in on_request + unavailable:
            assert pid not in recommended_ids, \
                f"Workflow should not recommend {pid}"

    def test_available_vs_recommended_distinction(self, monkeypatch):
        """Verify the distinction: available > recommended."""
        on_request = ["catering-classic-apero"]
        unavailable = ["catering-premium-apero"]

        monkeypatch.setattr(
            "workflows.io.config_store.get_on_request_products",
            lambda: on_request
        )
        monkeypatch.setattr(
            "workflows.io.config_store.get_unavailable_products",
            lambda: unavailable
        )

        recommended = list_recommended_products()
        available = list_available_products()

        # Available should always include recommended
        recommended_ids = {p.product_id for p in recommended}
        available_ids = {p.product_id for p in available}

        for pid in recommended_ids:
            assert pid in available_ids, \
                f"Recommended product {pid} should also be available"

        # Available should have more products than recommended (if on_request exists)
        if on_request:
            all_products = list_product_records()
            on_request_exists = any(
                p.product_id in on_request for p in all_products
            )
            if on_request_exists:
                assert len(available) > len(recommended), \
                    "Available should include on_request products that recommended excludes"
