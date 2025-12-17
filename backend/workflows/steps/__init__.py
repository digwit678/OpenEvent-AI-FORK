"""
Workflow Steps Module

This module contains the workflow step implementations, organized by step number.
Each step handles a specific phase of the event booking workflow.

Steps:
    step1_intake       - Initial client contact and information gathering
    step2_date_confirmation - Date negotiation and confirmation (future)
    step3_room_availability - Room selection and availability (future)
    step4_offer        - Offer generation and presentation (future)
    step5_negotiation  - Offer negotiation and acceptance (future)
    step6_transition   - Transition checkpoint (future)
    step7_confirmation - Final confirmation and booking (future)

MIGRATION NOTE:
    This module replaces backend.workflows.groups/ with clearer step-based naming.
    The old groups/ location re-exports from here for backwards compatibility.
"""

from backend.workflows.steps import step1_intake

__all__ = [
    "step1_intake",
]
