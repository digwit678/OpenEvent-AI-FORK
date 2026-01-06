"""
DEPRECATED: Use backend.workflows.steps.step2_date_confirmation.llm.analysis instead.

This module re-exports from the new canonical location for backwards compatibility.
"""

from workflows.steps.step2_date_confirmation.llm.analysis import (
    compose_date_confirmation_reply,
)

__all__ = ["compose_date_confirmation_reply"]
