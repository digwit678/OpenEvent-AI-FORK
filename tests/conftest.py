"""Pytest configuration for backend tests."""

import os
import sys

# Ensure project root is in path for imports
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Force plain verbalizer tone for deterministic test output
os.environ.setdefault("VERBALIZER_TONE", "plain")
