"""Test fixtures ensuring deterministic environment configuration."""

from __future__ import annotations

import os
import time


os.environ.setdefault("TZ", "Europe/Zurich")
os.environ.setdefault("PYTHONHASHSEED", "1337")

try:
    time.tzset()
except AttributeError:
    pass

collect_ignore_glob = ["test_*.py", "*_test.py"]

