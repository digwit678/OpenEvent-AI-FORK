"""
DEPRECATED: Use backend.core.fallback instead.

This module re-exports from core.fallback for backward compatibility.
All fallback logic is now consolidated in backend/core/fallback.py.

Migration guide:
    # Old import:
    from workflows.common.fallback_reason import FallbackReason, create_fallback_reason

    # New import:
    from core.fallback import FallbackContext, create_fallback_context
"""

from core.fallback import (
    # The canonical class (FallbackReason is an alias)
    FallbackContext,
    FallbackReason,
    # Toggle
    SHOW_FALLBACK_DIAGNOSTICS,
    # Functions
    format_fallback_diagnostic,
    append_fallback_diagnostic,
    create_fallback_reason,
    wrap_fallback,
    # Factory functions (both naming conventions)
    llm_disabled_reason,
    llm_exception_reason,
    empty_results_reason,
    llm_disabled_fallback,
    llm_exception_fallback,
    empty_results_fallback,
    low_confidence_fallback,
    create_fallback_context,
)

__all__ = [
    "FallbackReason",
    "FallbackContext",
    "SHOW_FALLBACK_DIAGNOSTICS",
    "format_fallback_diagnostic",
    "append_fallback_diagnostic",
    "create_fallback_reason",
    "wrap_fallback",
    "llm_disabled_reason",
    "llm_exception_reason",
    "empty_results_reason",
    "llm_disabled_fallback",
    "llm_exception_fallback",
    "empty_results_fallback",
    "low_confidence_fallback",
    "create_fallback_context",
]
