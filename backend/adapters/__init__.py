"""Adapter layer exposing integrations for the workflow."""

from .agent_adapter import AgentAdapter, StubAgentAdapter, get_agent_adapter
from .calendar_adapter import CalendarAdapter, ensure_calendar_dir
from .client_gui_adapter import ClientGUIAdapter

__all__ = [
    "AgentAdapter",
    "StubAgentAdapter",
    "get_agent_adapter",
    "CalendarAdapter",
    "ensure_calendar_dir",
    "ClientGUIAdapter",
]
