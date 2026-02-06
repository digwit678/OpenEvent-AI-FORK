from workflows.common.country_timezone import normalize_country_name, resolve_timezone
from workflows.io.config_store import get_timezone
from workflows.io.database import (
    ensure_event_defaults,
    get_default_db,
    resolve_client_timezone_context,
    upsert_client,
)
from workflows.io.timezone_context import reset_timezone_context, set_timezone_context


def test_country_alias_resolution():
    assert normalize_country_name("CH") == "switzerland"
    assert resolve_timezone("CH", None) == "Europe/Zurich"


def test_profile_timezone_overrides_country_default():
    db = get_default_db()
    client = upsert_client(db, "timezone-user@example.com", "TZ User")
    client["profile"]["country"] = "United States"
    client["profile"]["timezone"] = "America/Los_Angeles"

    ctx = resolve_client_timezone_context(db, "timezone-user@example.com")
    assert ctx["country"] == "united states"
    assert ctx["timezone"] == "America/Los_Angeles"


def test_profile_country_maps_to_default_timezone_when_timezone_missing():
    db = get_default_db()
    client = upsert_client(db, "country-user@example.com", "Country User")
    client["profile"]["country"] = "Italy"

    ctx = resolve_client_timezone_context(db, "country-user@example.com")
    assert ctx["country"] == "italy"
    assert ctx["timezone"] == "Europe/Rome"


def test_get_timezone_uses_request_context_override():
    baseline = get_timezone()
    tokens = set_timezone_context(
        email="context-user@example.com",
        country="united states",
        timezone="America/Los_Angeles",
    )
    try:
        assert get_timezone() == "America/Los_Angeles"
    finally:
        reset_timezone_context(tokens)
    assert get_timezone() == baseline


def test_event_defaults_include_client_country_timezone():
    event = {}
    ensure_event_defaults(event)
    assert "client_country" in event
    assert "client_timezone" in event
