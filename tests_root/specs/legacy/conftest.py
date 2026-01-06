from pathlib import Path


def pytest_ignore_collect(path, config):  # pragma: no cover - pytest hook
    """Keep legacy specs available for reference but out of the active suite."""

    base = Path(__file__).parent
    try:
        candidate = Path(str(path))
    except TypeError:
        return False
    return candidate == base or base in candidate.parents


__all__ = ["pytest_ignore_collect"]
