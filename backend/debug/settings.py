from __future__ import annotations

import os


_DEFAULT_TRACE = os.getenv("DEBUG_TRACE_DEFAULT", "1")

# Ensure the process environment always reflects the effective default so that
# child helpers querying os.environ inherit the same behaviour.
os.environ.setdefault("DEBUG_TRACE", _DEFAULT_TRACE)


def is_trace_enabled() -> bool:
    """Return whether workflow tracing is active."""

    return os.getenv("DEBUG_TRACE", _DEFAULT_TRACE) == "1"


__all__ = ["is_trace_enabled"]