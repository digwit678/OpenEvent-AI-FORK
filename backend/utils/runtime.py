"""Shared helpers to reset in-memory caches between test runs."""

from backend.adapters.agent_adapter import reset_agent_adapter
from backend.adapters.calendar_adapter import reset_calendar_adapter
from backend.config import reset_llm_profile_cache
from backend.workflows.common.requirements import clear_hash_caches
from backend.workflows.common.room_rules import clear_room_rule_cache
from backend.workflows.io.database import clear_cached_rooms
from backend.workflows.llm import adapter as llm_adapter


def reset_runtime_state() -> None:
    """Clear cached adapters and deterministic helpers."""

    reset_agent_adapter()
    reset_calendar_adapter()
    llm_adapter.reset_llm_adapter()
    clear_hash_caches()
    clear_room_rule_cache()
    clear_cached_rooms()
    reset_llm_profile_cache()


__all__ = ["reset_runtime_state"]
