from __future__ import annotations

import os

# Environment mode detection: dev vs prod
# In dev mode, debug tracing is enabled by default
# In prod mode, debug tracing is disabled by default (can still be explicitly enabled)
_IS_DEV = os.getenv("ENV", "dev").lower() in ("dev", "development", "local")

# Default trace setting: enabled in dev, disabled in prod
# Can be overridden by explicit DEBUG_TRACE_DEFAULT env var
_DEFAULT_TRACE = os.getenv("DEBUG_TRACE_DEFAULT", "1" if _IS_DEV else "0")

# Ensure the process environment always reflects the effective default so that
# child helpers querying os.environ inherit the same behaviour.
os.environ.setdefault("DEBUG_TRACE", _DEFAULT_TRACE)


def is_trace_enabled() -> bool:
    """Return whether workflow tracing is active."""

    return os.getenv("DEBUG_TRACE", _DEFAULT_TRACE) == "1"


__all__ = ["is_trace_enabled"]