"""
Tests for menu content abbreviation logic.

This module tests the dynamic abbreviation of menu content when it exceeds
the display threshold, and the link generation for detailed info pages.
"""

from __future__ import annotations

import pytest

from backend.workflows.common.menu_options import (
    MENU_CONTENT_CHAR_THRESHOLD,
    build_menu_title,
    extract_menu_request,
    format_menu_line,
    format_menu_line_short,
    select_menu_options,
)
from backend.utils.pseudolinks import generate_qna_link


@pytest.mark.v4
class TestFormatMenuLineShort:
    """Tests for the abbreviated menu format."""

    def test_short_format_returns_name_and_price(self):
        menu = {
            "menu_name": "Test Menu",
            "price": "CHF 100",
            "description": "A long description that should not appear in short format.",
        }
        result = format_menu_line_short(menu)
        assert "Test Menu" in result
        assert "CHF 100" in result
        assert "long description" not in result

    def test_short_format_includes_rooms_all(self):
        menu = {"menu_name": "Test", "price": "CHF 50"}
        result = format_menu_line_short(menu)
        assert "(Rooms: all)" in result

    def test_short_format_handles_missing_price(self):
        menu = {"menu_name": "Test Menu", "price": None}
        result = format_menu_line_short(menu)
        assert "Test Menu" in result
        assert "CHF ?" in result

    def test_short_format_returns_empty_for_missing_name(self):
        menu = {"menu_name": "", "price": "CHF 100"}
        result = format_menu_line_short(menu)
        assert result == ""


@pytest.mark.v4
class TestMenuContentThreshold:
    """Tests for the content threshold logic."""

    def test_threshold_value_is_reasonable(self):
        """400 chars is a reasonable UX threshold for chat messages."""
        assert MENU_CONTENT_CHAR_THRESHOLD == 400

    def test_full_format_exceeds_threshold_for_multiple_menus(self):
        """Full menu format with 3 menus should exceed the threshold."""
        request = {"menu_requested": True, "wine_pairing": True}
        options = select_menu_options(request, limit=3)

        full_lines = [build_menu_title(request)]
        for option in options:
            full_lines.append(format_menu_line(option))

        combined_len = len("\n".join(full_lines))
        assert combined_len > MENU_CONTENT_CHAR_THRESHOLD

    def test_short_format_stays_under_threshold_for_multiple_menus(self):
        """Short menu format with 3 menus should stay under the threshold."""
        request = {"menu_requested": True, "wine_pairing": True}
        options = select_menu_options(request, limit=3)

        short_lines = [build_menu_title(request)]
        for option in options:
            short_lines.append(format_menu_line_short(option))

        combined_len = len("\n".join(short_lines))
        assert combined_len < MENU_CONTENT_CHAR_THRESHOLD


@pytest.mark.v4
class TestCateringLinkGeneration:
    """Tests for catering info page link generation."""

    def test_link_includes_category(self):
        link = generate_qna_link("Catering")
        assert "category=Catering" in link

    def test_link_includes_query_params(self):
        params = {"month": "february", "vegetarian": "true"}
        link = generate_qna_link("Catering", query_params=params)
        assert "month=february" in link
        assert "vegetarian=true" in link

    def test_link_is_html_anchor(self):
        link = generate_qna_link("Catering")
        assert link.startswith("<a href=")
        assert 'target="_blank"' in link

    def test_link_includes_info_qna_path(self):
        link = generate_qna_link("Catering")
        assert "/info/qna" in link


@pytest.mark.v4
class TestMenuRequestExtraction:
    """Tests for extracting menu request from user message."""

    def test_extracts_menu_with_wine_pairing(self):
        message = "What menus with wine pairings do you have?"
        request = extract_menu_request(message)
        assert request is not None
        assert request.get("wine_pairing") is True

    def test_extracts_month_from_message(self):
        message = "Show me February menu options"
        request = extract_menu_request(message)
        assert request is not None
        assert request.get("month") == "february"

    def test_extracts_vegetarian_preference(self):
        message = "Do you have vegetarian menu options?"
        request = extract_menu_request(message)
        assert request is not None
        assert request.get("vegetarian") is True
