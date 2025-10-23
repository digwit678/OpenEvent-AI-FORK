"""Lightweight JSON helpers with an optional orjson fast path.

The helpers default to the standard library `json` module to avoid adding
dependencies. When `orjson` happens to be installed in the environment,
`loads` uses it automatically for speed; `dumps` falls back to the stdlib
whenever parameters (like `indent`) are unsupported by `orjson`.
"""

from __future__ import annotations

import json
from typing import Any, IO, Mapping, Sequence

try:  # Optional fast path; no hard dependency.
    import orjson  # type: ignore[import]
except ImportError:  # pragma: no cover - exercised only when orjson missing.
    orjson = None  # type: ignore[assignment]


def loads(data: str | bytes, *, parse_float=None, parse_int=None, parse_constant=None, object_hook=None) -> Any:
    """Deserialize JSON using `orjson` when available and compatible."""

    if orjson is not None and parse_float is None and parse_int is None and parse_constant is None and object_hook is None:
        return orjson.loads(data)  # type: ignore[no-any-return]
    return json.loads(
        data,
        parse_float=parse_float,
        parse_int=parse_int,
        parse_constant=parse_constant,
        object_hook=object_hook,
    )


def dumps(
    obj: Any,
    *,
    indent: int | None = None,
    sort_keys: bool = False,
    ensure_ascii: bool = True,
    separators: tuple[str, str] | None = None,
) -> str:
    """Serialize JSON, delegating to `orjson` when parameters permit."""

    if orjson is not None and indent is None and separators is None and ensure_ascii:
        option = 0
        if sort_keys:
            option |= orjson.OPT_SORT_KEYS  # type: ignore[attr-defined]
        return orjson.dumps(obj, option=option).decode("utf-8")  # type: ignore[no-any-return]
    return json.dumps(obj, indent=indent, sort_keys=sort_keys, ensure_ascii=ensure_ascii, separators=separators)


def load(handle: IO[str]) -> Any:
    """File-object variant of `loads` retaining stdlib compatibility."""

    return json.load(handle)


def dump(
    obj: Any,
    handle: IO[str],
    *,
    indent: int | None = None,
    sort_keys: bool = False,
    ensure_ascii: bool = True,
) -> None:
    """File-object variant of `dumps` with the stdlib semantics."""

    json.dump(obj, handle, indent=indent, sort_keys=sort_keys, ensure_ascii=ensure_ascii)


__all__ = ["load", "loads", "dump", "dumps"]
