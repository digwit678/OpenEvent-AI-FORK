"""Utility helpers for OpenEvent backend components.

This package intentionally keeps its public surface minimal so individual
helpers (profiling, async execution, JSON I/O) can be imported without
pulling heavier workflow modules. Tests that need to reset runtime caches
can import `backend.utils.runtime` for explicit reset hooks.
"""

__all__ = ["async_tools", "json_io", "profiler", "runtime"]
