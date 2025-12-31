"""
MODULE: backend/core/fallback.py
PURPOSE: Fallback message wrapping with mandatory diagnostics.

Every fallback message MUST go through this module. This ensures:
1. Testers can immediately see THAT a message is a fallback
2. Testers can see WHY the fallback was triggered
3. Debugging is faster because context is preserved

DEPENDS ON:
    - backend/debug/trace.py  # For emitting fallback events

USED BY:
    - backend/workflows/llm/adapter.py           # LLM fallback
    - backend/workflows/qna/verbalizer.py        # Q&A fallback
    - backend/workflows/common/general_qna.py    # Structured Q&A fallback
    - backend/workflows/groups/*/trigger/*.py    # Step-specific fallbacks

ENVIRONMENT:
    OE_FALLBACK_DIAGNOSTICS=false  # Hide diagnostics (default, production-safe)
    OE_FALLBACK_DIAGNOSTICS=true   # Show full diagnostics (dev/staging only)

OUTPUT FORMAT (when diagnostics enabled):

    ---
    [FALLBACK: detection.intent.classifier]
    Trigger: low_confidence (0.12)
    Attempted: classify_intent(message='asdfgh...')
    Step: 2 | Thread: abc123
    ---

    {original fallback message}
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional

# Default to hiding diagnostics (production-safe). Set OE_FALLBACK_DIAGNOSTICS=true for dev.
SHOW_FALLBACK_DIAGNOSTICS = os.environ.get("OE_FALLBACK_DIAGNOSTICS", "false").lower() in (
    "true",
    "1",
    "yes",
)


@dataclass
class FallbackContext:
    """
    Structured context for fallback messages.

    All fallback paths must create a FallbackContext to document
    what was attempted and why the fallback was triggered.
    """

    source: str  # e.g., "detection.intent.classifier", "qna.verbalizer"
    trigger: str  # e.g., "low_confidence", "llm_exception", "empty_results", "no_match"
    step: Optional[int] = None
    thread_id: Optional[str] = None
    event_id: Optional[str] = None

    # What was attempted
    attempted: Optional[str] = None  # e.g., "classify_intent(message='hello world')"
    confidence: Optional[float] = None

    # Error information
    error_type: Optional[str] = None  # e.g., "TimeoutError"
    error_message: Optional[str] = None

    # Failed conditions (what checks failed)
    failed_conditions: list = field(default_factory=list)

    # Additional context
    context: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization/logging."""
        return {
            "source": self.source,
            "trigger": self.trigger,
            "step": self.step,
            "thread_id": self.thread_id,
            "event_id": self.event_id,
            "attempted": self.attempted,
            "confidence": self.confidence,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "failed_conditions": self.failed_conditions,
            "context": self.context,
        }

    def format_diagnostic(self) -> str:
        """Format the diagnostic block for display."""
        lines = [
            "---",
            f"[FALLBACK: {self.source}]",
        ]

        # Trigger line with confidence if available
        trigger_line = f"Trigger: {self.trigger}"
        if self.confidence is not None:
            trigger_line += f" ({self.confidence:.2f})"
        lines.append(trigger_line)

        # Error information if present
        if self.error_type:
            error_line = f"Error: {self.error_type}"
            if self.error_message:
                # Truncate long error messages
                msg = self.error_message[:100]
                if len(self.error_message) > 100:
                    msg += "..."
                error_line += f" - {msg}"
            lines.append(error_line)

        # What was attempted
        if self.attempted:
            # Truncate long attempted strings
            attempted = self.attempted[:80]
            if len(self.attempted) > 80:
                attempted += "..."
            lines.append(f"Attempted: {attempted}")

        # Step and thread info
        info_parts = []
        if self.step is not None:
            info_parts.append(f"Step: {self.step}")
        if self.thread_id:
            info_parts.append(f"Thread: {self.thread_id[:12]}")
        if self.event_id:
            info_parts.append(f"Event: {self.event_id[:12]}")
        if info_parts:
            lines.append(" | ".join(info_parts))

        # Failed conditions
        if self.failed_conditions:
            lines.append(f"Failed: {', '.join(self.failed_conditions)}")

        # Additional context
        if self.context:
            context_str = ", ".join(f"{k}={v}" for k, v in self.context.items())
            if len(context_str) > 100:
                context_str = context_str[:100] + "..."
            lines.append(f"Context: {context_str}")

        lines.append("---")
        return "\n".join(lines)


def wrap_fallback(message: str, context: FallbackContext) -> str:
    """
    Wrap a fallback message with diagnostic information.

    This function MUST be called for all fallback messages to ensure
    visibility of fallback conditions.

    Args:
        message: The original fallback message
        context: FallbackContext with diagnostic information

    Returns:
        Message with diagnostic block prepended (if diagnostics enabled)

    Example:
        context = FallbackContext(
            source="detection.intent.classifier",
            trigger="low_confidence",
            confidence=0.12,
            step=2,
            attempted="classify_intent(message='asdfgh')"
        )
        wrapped = wrap_fallback("I'm not sure I understand.", context)
    """
    if not SHOW_FALLBACK_DIAGNOSTICS:
        return message

    diagnostic = context.format_diagnostic()
    return f"{diagnostic}\n\n{message}"


def create_fallback_context(
    source: str,
    trigger: str,
    *,
    step: Optional[int] = None,
    thread_id: Optional[str] = None,
    event_id: Optional[str] = None,
    attempted: Optional[str] = None,
    confidence: Optional[float] = None,
    error: Optional[Exception] = None,
    failed_conditions: Optional[list] = None,
    **context_kwargs: Any,
) -> FallbackContext:
    """
    Factory function to create FallbackContext with common patterns.

    Args:
        source: Module identifier
        trigger: Trigger reason
        step: Current workflow step
        thread_id: Thread ID
        event_id: Event ID
        attempted: What was attempted
        confidence: Confidence score
        error: Exception if this is an error fallback
        failed_conditions: List of checks that failed
        **context_kwargs: Additional context key-value pairs

    Returns:
        Configured FallbackContext
    """
    return FallbackContext(
        source=source,
        trigger=trigger,
        step=step,
        thread_id=thread_id,
        event_id=event_id,
        attempted=attempted,
        confidence=confidence,
        error_type=type(error).__name__ if error else None,
        error_message=str(error) if error else None,
        failed_conditions=failed_conditions or [],
        context=context_kwargs,
    )


# Pre-defined fallback context factories for common cases


def llm_disabled_fallback(
    source: str,
    *,
    step: Optional[int] = None,
    thread_id: Optional[str] = None,
) -> FallbackContext:
    """Fallback context for when LLM is disabled."""
    return create_fallback_context(
        source=source,
        trigger="llm_disabled",
        step=step,
        thread_id=thread_id,
        reason="OPENAI_API_KEY not set or AGENT_MODE=stub",
    )


def llm_exception_fallback(
    source: str,
    error: Exception,
    *,
    step: Optional[int] = None,
    thread_id: Optional[str] = None,
    attempted: Optional[str] = None,
) -> FallbackContext:
    """Fallback context for LLM exceptions."""
    return create_fallback_context(
        source=source,
        trigger="llm_exception",
        step=step,
        thread_id=thread_id,
        attempted=attempted,
        error=error,
    )


def empty_results_fallback(
    source: str,
    *,
    step: Optional[int] = None,
    thread_id: Optional[str] = None,
    query: Optional[str] = None,
    **counts: int,
) -> FallbackContext:
    """Fallback context for empty query results."""
    return create_fallback_context(
        source=source,
        trigger="empty_results",
        step=step,
        thread_id=thread_id,
        query=query,
        **counts,
    )


def low_confidence_fallback(
    source: str,
    confidence: float,
    *,
    step: Optional[int] = None,
    thread_id: Optional[str] = None,
    message_preview: Optional[str] = None,
) -> FallbackContext:
    """Fallback context for low confidence classification."""
    return create_fallback_context(
        source=source,
        trigger="low_confidence",
        step=step,
        thread_id=thread_id,
        confidence=confidence,
        message_preview=message_preview[:50] if message_preview else None,
    )


# Known fallback message patterns (for detection/testing)
KNOWN_FALLBACK_PATTERNS = [
    "no specific information available",
    "sorry, cannot handle",
    "unable to process",
    "i don't understand",
    "there appears to be no",
    "it appears there is no",
    "i cannot help with this",
    "unable to assist",
    "not sure what you mean",
]


def is_likely_fallback(message: str) -> bool:
    """
    Check if a message looks like a fallback response.

    Useful for testing and monitoring to detect when the system
    is falling back to generic responses.

    Args:
        message: Message to check

    Returns:
        True if message contains known fallback patterns
    """
    message_lower = message.lower()
    return any(pattern in message_lower for pattern in KNOWN_FALLBACK_PATTERNS)


# =============================================================================
# Backward Compatibility Aliases
# =============================================================================
# These aliases support code that imports from the old fallback_reason module.
# The canonical names are FallbackContext and wrap_fallback.

# Alias for backward compatibility with fallback_reason.py imports
FallbackReason = FallbackContext


def format_fallback_diagnostic(context: FallbackContext) -> str:
    """Format a fallback context into a diagnostic string (alias for context.format_diagnostic())."""
    return context.format_diagnostic()


def append_fallback_diagnostic(body: str, context: FallbackContext) -> str:
    """
    Append fallback diagnostic info to a message body.

    Only appends if SHOW_FALLBACK_DIAGNOSTICS is True.
    This is an alternative to wrap_fallback which prepends.
    """
    if not SHOW_FALLBACK_DIAGNOSTICS:
        return body
    diagnostic = context.format_diagnostic()
    return body + "\n\n" + diagnostic


def create_fallback_reason(
    source: str,
    trigger: str,
    *,
    failed_conditions: Optional[list] = None,
    context: Optional[dict] = None,
    original_error: Optional[str] = None,
) -> FallbackContext:
    """
    Create a FallbackContext using the old FallbackReason API.

    This is for backward compatibility with code using fallback_reason.py.
    Prefer create_fallback_context for new code.
    """
    return FallbackContext(
        source=source,
        trigger=trigger,
        failed_conditions=failed_conditions or [],
        context=context or {},
        error_message=original_error,
    )


# Alias factories with _reason suffix for backward compatibility
def llm_disabled_reason(source: str) -> FallbackContext:
    """Create a fallback for when LLM is disabled (backward compat alias)."""
    return llm_disabled_fallback(source)


def llm_exception_reason(source: str, error: Exception) -> FallbackContext:
    """Create a fallback for LLM exceptions (backward compat alias)."""
    return llm_exception_fallback(source, error)


def empty_results_reason(
    source: str,
    rooms_count: int = 0,
    dates_count: int = 0,
    products_count: int = 0,
) -> FallbackContext:
    """Create a fallback for empty query results (backward compat alias)."""
    return empty_results_fallback(
        source,
        rooms_count=rooms_count,
        dates_count=dates_count,
        products_count=products_count,
    )
