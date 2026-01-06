from datetime import date

from workflows.common.datetime_parse import parse_first_date


def test_parse_first_date_prefers_numeric() -> None:
    content = "Let's meet on 12.03.2027, that's confirmed."
    result = parse_first_date(content)
    assert result == date(2027, 3, 12)


def test_parse_first_date_resolves_next_week_reference() -> None:
    reference = date(2027, 3, 8)  # Monday
    content = "Friday next week works great."
    result = parse_first_date(content, reference=reference)
    assert result == date(2027, 3, 19)


def test_parse_first_date_resolves_month_and_week_ordinal() -> None:
    reference = date(2027, 9, 25)
    content = "Friday in the first October week sounds perfect."
    result = parse_first_date(content, reference=reference)
    assert result == date(2027, 10, 1)
