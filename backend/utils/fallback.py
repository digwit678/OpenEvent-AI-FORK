"""
DEPRECATED: Use backend.core.fallback instead.

This module re-exports from backend.core.fallback for backward compatibility.
All fallback logic is now consolidated in backend/core/fallback.py.

Migration guide:
    # Old import:
    from backend.utils.fallback import create_fallback_context, wrap_fallback

    # New import:
    from backend.core.fallback import create_fallback_context, wrap_fallback
"""

import warnings

warnings.warn(
    "backend.utils.fallback is deprecated. Use backend.core.fallback instead.",
    DeprecationWarning,
    stacklevel=2,
)

from backend.core.fallback import (
    # Core exports
    FallbackContext,
    SHOW_FALLBACK_DIAGNOSTICS,
    wrap_fallback,
    create_fallback_context,
    is_likely_fallback,
    KNOWN_FALLBACK_PATTERNS,
    # Factory functions
    llm_disabled_fallback,
    llm_exception_fallback,
    empty_results_fallback,
    low_confidence_fallback,
    # Backward compat aliases
    FallbackReason,
    format_fallback_diagnostic,
    append_fallback_diagnostic,
    create_fallback_reason,
    llm_disabled_reason,
    llm_exception_reason,
    empty_results_reason,
)

__all__ = [
    "FallbackContext",
    "FallbackReason",
    "SHOW_FALLBACK_DIAGNOSTICS",
    "wrap_fallback",
    "create_fallback_context",
    "is_likely_fallback",
    "KNOWN_FALLBACK_PATTERNS",
    "llm_disabled_fallback",
    "llm_exception_fallback",
    "empty_results_fallback",
    "low_confidence_fallback",
    "format_fallback_diagnostic",
    "append_fallback_diagnostic",
    "create_fallback_reason",
    "llm_disabled_reason",
    "llm_exception_reason",
    "empty_results_reason",
]
