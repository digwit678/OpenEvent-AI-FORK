from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Optional

__workflow_role__ = "TimezoneContext"

_CURRENT_EMAIL: ContextVar[Optional[str]] = ContextVar("oe_current_email", default=None)
_CURRENT_COUNTRY: ContextVar[Optional[str]] = ContextVar("oe_current_country", default=None)
_CURRENT_TIMEZONE: ContextVar[Optional[str]] = ContextVar("oe_current_timezone", default=None)


@dataclass
class TimezoneContextTokens:
    email: Token
    country: Token
    timezone: Token


def set_timezone_context(
    *,
    email: Optional[str],
    country: Optional[str],
    timezone: Optional[str],
) -> TimezoneContextTokens:
    """Set request-scoped timezone context and return reset tokens."""
    return TimezoneContextTokens(
        email=_CURRENT_EMAIL.set(email),
        country=_CURRENT_COUNTRY.set(country),
        timezone=_CURRENT_TIMEZONE.set(timezone),
    )


def reset_timezone_context(tokens: TimezoneContextTokens) -> None:
    """Reset request-scoped timezone context."""
    _CURRENT_EMAIL.reset(tokens.email)
    _CURRENT_COUNTRY.reset(tokens.country)
    _CURRENT_TIMEZONE.reset(tokens.timezone)


def get_current_timezone() -> Optional[str]:
    """Get request-scoped timezone if available."""
    return _CURRENT_TIMEZONE.get()


def get_current_country() -> Optional[str]:
    """Get request-scoped country if available."""
    return _CURRENT_COUNTRY.get()


def get_current_email() -> Optional[str]:
    """Get request-scoped client email if available."""
    return _CURRENT_EMAIL.get()
