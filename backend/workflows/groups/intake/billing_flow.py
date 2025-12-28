"""
DEPRECATED: Use backend.workflows.steps.step1_intake.billing_flow instead.

This module re-exports from the new canonical location for backwards compatibility.
"""

from backend.workflows.steps.step1_intake.billing_flow import handle_billing_capture

__all__ = ["handle_billing_capture"]
