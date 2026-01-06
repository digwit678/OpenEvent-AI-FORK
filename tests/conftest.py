"""Pytest configuration for backend tests."""

import os

# Force plain verbalizer tone for deterministic test output
os.environ.setdefault("VERBALIZER_TONE", "plain")
