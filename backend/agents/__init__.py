"""
Agent orchestration package for OpenEvent.

This package hosts the scaffolding used to connect the deterministic workflow
pipeline with the OpenAI Agents SDK.  The initial implementation focuses on
thin wrappers around existing workflow functions so we can progressively move
tool execution into agent-managed calls without duplicating business logic.
"""

from __future__ import annotations

from .openevent_agent import OpenEventAgent  # noqa: F401
from .chatkit_runner import build_agent, run_streamed, validate_tool_call, StepToolPolicy, ToolExecutionError  # noqa: F401

__all__ = [
    "OpenEventAgent",
    "build_agent",
    "run_streamed",
    "validate_tool_call",
    "StepToolPolicy",
    "ToolExecutionError",
]
