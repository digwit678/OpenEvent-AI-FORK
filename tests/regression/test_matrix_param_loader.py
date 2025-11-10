"""Regression test ensuring the matrix lock parameters stay deterministic."""

from __future__ import annotations

import json
from pathlib import Path


LOCK_PATH = Path(__file__).with_name("test_matrix_lock.json")


def load_matrix() -> dict:
    with LOCK_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def test_matrix_lock_structure() -> None:
    data = load_matrix()
    assert set(data.keys()) == {"python", "platform", "features", "generated_at"}
    assert all(isinstance(version, str) for version in data["python"])
    assert all(version.count(".") == 1 for version in data["python"])
    assert data["platform"] == ["ubuntu-latest"]
    assert "workflow" in data["features"]