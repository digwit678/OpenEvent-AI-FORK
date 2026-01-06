"""
DEPRECATED: Use backend.workflows.steps.step1_intake.llm.analysis instead.

This module re-exports from the new canonical location for backwards compatibility.
"""

from backend.workflows.steps.step1_intake.llm.analysis import (
    classify_intent,
    extract_user_information,
    sanitize_user_info,
)

__all__ = ["classify_intent", "extract_user_information", "sanitize_user_info"]
