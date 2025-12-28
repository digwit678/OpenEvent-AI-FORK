"""Legacy conversation helpers - minimal re-export shim.

DEPRECATED: This module is kept only for backward compatibility.

The chatbot logic that was here has been completely replaced by:
- Intent classification: backend/detection/intent/
- Entity extraction: backend/workflows/steps/step1_intake/
- Conversation flow: backend/workflow_email.py (orchestrator)
- Step handlers: backend/workflows/steps/step{1-7}*/

Session store functions (active_conversations, render_step3_reply, pop_step3_payload)
have been moved to backend/legacy/session_store.py as part of C1 refactoring (Dec 2025).

Legacy chatbot functions (generate_response, classify_email, extract_information_incremental,
create_offer_summary, etc.) have been removed as part of C2 cleanup (Dec 2025).
A historical copy exists at backend/DEPRECATED/conversation_manager_v0.py.
"""

# C1: Re-export session store functions for backward compatibility
from backend.legacy.session_store import (
    active_conversations,
    STEP3_DRAFT_CACHE,
    STEP3_PAYLOAD_CACHE,
    render_step3_reply,
    pop_step3_payload,
)

__all__ = [
    "active_conversations",
    "STEP3_DRAFT_CACHE",
    "STEP3_PAYLOAD_CACHE",
    "render_step3_reply",
    "pop_step3_payload",
]
