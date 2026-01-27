"""
Backwards-compatible entry point for the OpenEvent-AI backend.

This module provides backwards compatibility for existing imports and commands:
- `from main import app` works (re-exports from app.py)
- `uvicorn main:app` works (app is re-exported)
- `python main.py` works (delegates to dev_main.py)

For new code, prefer:
- Production: `from app import app` or `uvicorn app:app`
- Development: `python scripts/dev/dev_main.py`
"""

# Re-export the app for backwards compatibility
# This allows `uvicorn main:app` to continue working
from app import app, create_app

# Re-export commonly used utilities for backwards compatibility
from workflow_email import DB_PATH as WF_DB_PATH
from utils import json_io
from pathlib import Path

# Legacy paths (for backwards compat in any string contexts)
EVENTS_FILE = str(WF_DB_PATH)


def load_events_database():
    """Load all events from the database file."""
    if WF_DB_PATH.exists():
        with open(WF_DB_PATH, 'r', encoding='utf-8') as f:
            return json_io.load(f)
    return {"events": []}


def save_events_database(database):
    """Save all events to the database file."""
    with open(WF_DB_PATH, 'w', encoding='utf-8') as f:
        json_io.dump(database, f, indent=2, ensure_ascii=False)


# When run directly, delegate to dev_main.py for all dev behaviors
if __name__ == "__main__":
    # Import and run dev_main which handles:
    # - Cache clearing
    # - Environment setup
    # - Frontend auto-launch
    # - Browser auto-open
    # - Port cleanup
    import sys
    from pathlib import Path

    # Add scripts/dev to path
    scripts_dev = Path(__file__).parent / "scripts" / "dev"
    if str(scripts_dev) not in sys.path:
        sys.path.insert(0, str(scripts_dev))

    from dev_main import main
    main()
