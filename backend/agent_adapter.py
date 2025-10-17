"""Shim module re-exporting adapter classes from backend.adapters."""

# DEPRECATED: Legacy wrapper kept for compatibility. Do not add workflow logic here.
# Intake/Date/Availability live in backend/workflows/groups/* and are orchestrated by workflow_email.py.

from backend.adapters.agent_adapter import AgentAdapter, StubAgentAdapter, get_agent_adapter

__all__ = ["AgentAdapter", "StubAgentAdapter", "get_agent_adapter"]
