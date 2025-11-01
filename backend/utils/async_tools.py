"""Threaded helpers for lightweight parallel I/O.

The helpers in this module are intentionally conservative: they use the
standard library `concurrent.futures` primitives with a small default
worker pool so we can overlap blocking I/O (e.g. file reads) without
introducing new dependencies. Consumers should only dispatch tasks that



are safe to run in parallel.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait
from typing import Callable, Iterable, List, Sequence, TypeVar

T = TypeVar("T")


def run_io_tasks(tasks: Sequence[Callable[[], T]], max_workers: int = 4) -> List[T]:
    """Execute blocking I/O callables concurrently and return their results."""

    if not tasks:
        return []
    worker_count = max(1, min(int(max_workers), len(tasks)))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(task) for task in tasks]
        wait(futures)
    results: List[T] = []
    for future in futures:
        results.append(future.result())
    return results


__all__ = ["run_io_tasks"]
