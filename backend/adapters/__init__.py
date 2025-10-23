"""Adapter layer exposing integrations for the workflow."""

from .agent_adapter import AgentAdapter, StubAgentAdapter, get_agent_adapter, reset_agent_adapter
from .calendar_adapter import CalendarAdapter, ensure_calendar_dir, get_calendar_adapter, reset_calendar_adapter
from .client_gui_adapter import ClientGUIAdapter

__all__ = [
    "AgentAdapter",
    "StubAgentAdapter",
    "get_agent_adapter",
    "reset_agent_adapter",
    "CalendarAdapter",
    "get_calendar_adapter",
    "reset_calendar_adapter",
    "ensure_calendar_dir",
    "ClientGUIAdapter",
]
