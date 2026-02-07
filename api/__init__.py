"""FastAPI routers for the OpenEvent backend."""

from __future__ import annotations

__all__ = ["agent_router"]


def __getattr__(name: str):
    """Lazy-load router exports to keep package imports lightweight."""
    if name == "agent_router":
        from .agent_router import router as agent_router
        return agent_router
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
