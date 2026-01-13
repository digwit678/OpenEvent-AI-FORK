"""Unit tests for datetime_parse module - date extraction without explicit year."""

from datetime import date
from unittest.mock import patch

import pytest

from workflows.common.datetime_parse import parse_first_date


@pytest.mark.v4
class TestDateParsingWithoutYear:
    """Test that dates without year default to current year."""

    def test_dmy_with_of(self):
        """16th of February -> uses current year."""
        with patch("workflows.common.datetime_parse.date") as mock_date:
            mock_date.today.return_value = date(2026, 1, 13)
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
            result = parse_first_date("16th of February")
            assert result == date(2026, 2, 16)

    def test_dmy_without_of(self):
        """16th February -> uses current year."""
        with patch("workflows.common.datetime_parse.date") as mock_date:
            mock_date.today.return_value = date(2026, 1, 13)
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
            result = parse_first_date("16th February")
            assert result == date(2026, 2, 16)

    def test_dmy_plain(self):
        """16 February -> uses current year."""
        with patch("workflows.common.datetime_parse.date") as mock_date:
            mock_date.today.return_value = date(2026, 1, 13)
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
            result = parse_first_date("16 February")
            assert result == date(2026, 2, 16)

    def test_mdy_format(self):
        """February 16 -> uses current year."""
        with patch("workflows.common.datetime_parse.date") as mock_date:
            mock_date.today.return_value = date(2026, 1, 13)
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
            result = parse_first_date("February 16")
            assert result == date(2026, 2, 16)

    def test_with_ordinal_suffixes(self):
        """Various ordinal suffixes work correctly."""
        with patch("workflows.common.datetime_parse.date") as mock_date:
            mock_date.today.return_value = date(2026, 1, 13)
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
            assert parse_first_date("1st of March") == date(2026, 3, 1)
            assert parse_first_date("2nd of March") == date(2026, 3, 2)
            assert parse_first_date("3rd of March") == date(2026, 3, 3)
            assert parse_first_date("22nd of December") == date(2026, 12, 22)

    def test_explicit_year_overrides(self):
        """Explicit year is respected even if different from current."""
        # No mocking needed - explicit year is used
        assert parse_first_date("16th of February 2025") == date(2025, 2, 16)
        assert parse_first_date("February 16, 2027") == date(2027, 2, 16)

    def test_embedded_in_sentence(self):
        """Extract date from within a sentence."""
        with patch("workflows.common.datetime_parse.date") as mock_date:
            mock_date.today.return_value = date(2026, 1, 13)
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
            result = parse_first_date("We would like to book on 16th of February please")
            assert result == date(2026, 2, 16)

    def test_fallback_year_parameter(self):
        """fallback_year parameter is used when no year in text."""
        result = parse_first_date("16th February", fallback_year=2024)
        assert result == date(2024, 2, 16)


@pytest.mark.v4
class TestNumericDateFormats:
    """Test numeric date formats."""

    def test_ddmmyyyy(self):
        """16.02.2026 -> 2026-02-16"""
        assert parse_first_date("16.02.2026") == date(2026, 2, 16)

    def test_ddmmyy_adds_2000(self):
        """16.02.26 -> 2026-02-16 (2-digit year adds 2000)"""
        assert parse_first_date("16.02.26") == date(2026, 2, 16)

    def test_iso_format(self):
        """2026-02-16 -> 2026-02-16"""
        assert parse_first_date("2026-02-16") == date(2026, 2, 16)


@pytest.mark.v4
class TestOfKeywordRegression:
    """Regression tests for the 'of' keyword fix."""

    def test_all_of_variations(self):
        """Ensure 'of' keyword works in various positions."""
        # These all must parse correctly
        test_cases = [
            "16th of February 2026",
            "the 16th of February 2026",
            "on the 16 of February 2026",
            "for the 16th of Feb 2026",
        ]
        for phrase in test_cases:
            result = parse_first_date(phrase)
            assert result is not None, f"Failed to parse: {phrase}"
            assert result.day == 16, f"Wrong day for: {phrase}"
            assert result.month == 2, f"Wrong month for: {phrase}"
