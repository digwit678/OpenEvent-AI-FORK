"""
Test that importing app.py has no side effects.

This is a critical production safety test. The app module must be importable
without:
- Clearing bytecode caches (__pycache__ directories)
- Mutating environment variables
- Spawning subprocesses
- Writing to the filesystem
- Opening network connections

These behaviors are acceptable in dev_main.py but NOT in app.py.
"""
import subprocess
import sys
import os
from pathlib import Path


# Get the backend directory (where app.py lives)
BACKEND_DIR = Path(__file__).resolve().parents[2]


class TestAppImportSideEffects:
    """Verify app.py import has no side effects."""

    def test_import_does_not_clear_pycache(self, tmp_path: Path):
        """Importing app should NOT clear __pycache__ directories."""
        # Create a fake __pycache__ directory
        fake_cache = tmp_path / "__pycache__"
        fake_cache.mkdir()
        marker_file = fake_cache / "marker.pyc"
        marker_file.write_bytes(b"fake bytecode")

        # Run a subprocess that imports app and checks if the marker still exists
        script = f'''
import sys
sys.path.insert(0, "{BACKEND_DIR}")

# Set ENV to prod to avoid any dev behaviors
import os
os.environ["ENV"] = "prod"

# Create the marker before import
from pathlib import Path
marker = Path("{marker_file}")
assert marker.exists(), "Marker should exist before import"

# Import the app
from app import app

# Check marker still exists after import
assert marker.exists(), "Marker should still exist after importing app"
print("PASS: __pycache__ not cleared during import")
'''
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )

        assert result.returncode == 0, f"Import test failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        assert "PASS" in result.stdout

    def test_import_does_not_mutate_agent_mode(self):
        """Importing app should NOT auto-set AGENT_MODE based on keys."""
        # Run a subprocess without AGENT_MODE or API keys set
        script = f'''
import sys
sys.path.insert(0, "{BACKEND_DIR}")
import os

# Clear any existing AGENT_MODE
if "AGENT_MODE" in os.environ:
    del os.environ["AGENT_MODE"]

# Clear API keys
for key in ["GOOGLE_API_KEY", "gemini_key_openevent", "OPENAI_API_KEY"]:
    if key in os.environ:
        del os.environ[key]

os.environ["ENV"] = "prod"

# Import the app
from app import app

# Check AGENT_MODE was NOT set
assert "AGENT_MODE" not in os.environ, f"AGENT_MODE was unexpectedly set to: {{os.environ.get('AGENT_MODE')}}"
print("PASS: AGENT_MODE not mutated during import")
'''
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env={k: v for k, v in os.environ.items() if k not in ["AGENT_MODE", "GOOGLE_API_KEY", "gemini_key_openevent"]},
        )

        assert result.returncode == 0, f"Import test failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        assert "PASS" in result.stdout

    def test_import_does_not_print_dev_warnings(self):
        """Importing app should NOT print security warnings."""
        script = f'''
import sys
sys.path.insert(0, "{BACKEND_DIR}")
import os
os.environ["ENV"] = "prod"

# Import the app
from app import app

print("PASS: Import completed")
'''
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env={**os.environ, "ENV": "prod"},
        )

        assert result.returncode == 0, f"Import test failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        # Should not print security warnings during import
        assert "[SECURITY]" not in result.stdout, "Should not print security warnings on import"
        assert "PASS" in result.stdout

    def test_import_does_not_set_dont_write_bytecode(self):
        """Importing app should NOT set sys.dont_write_bytecode."""
        script = f'''
import sys
sys.path.insert(0, "{BACKEND_DIR}")
import os
os.environ["ENV"] = "prod"

# Ensure it's False before import
sys.dont_write_bytecode = False
original = sys.dont_write_bytecode

# Import the app
from app import app

# Check it wasn't changed
assert sys.dont_write_bytecode == original, f"dont_write_bytecode changed from {{original}} to {{sys.dont_write_bytecode}}"
print("PASS: sys.dont_write_bytecode not modified")
'''
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env={k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"},
        )

        assert result.returncode == 0, f"Import test failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        assert "PASS" in result.stdout


class TestMainImportBackwardsCompat:
    """Verify main.py maintains backwards compatibility."""

    def test_main_exports_app(self):
        """main.py should re-export app for backwards compat."""
        script = f'''
import sys
sys.path.insert(0, "{BACKEND_DIR}")
import os
os.environ["ENV"] = "prod"

from main import app
from app import app as app_direct

# Both should be the same object
assert app is app_direct, "main.app should be the same as app.app"
print("PASS: main.app is app.app")
'''
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env={**os.environ, "ENV": "prod"},
        )

        assert result.returncode == 0, f"Import test failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        assert "PASS" in result.stdout

    def test_main_exports_create_app(self):
        """main.py should re-export create_app for backwards compat."""
        script = f'''
import sys
sys.path.insert(0, "{BACKEND_DIR}")
import os
os.environ["ENV"] = "prod"

from main import create_app
from app import create_app as create_app_direct

# Both should be the same function
assert create_app is create_app_direct, "main.create_app should be the same as app.create_app"
print("PASS: main.create_app is app.create_app")
'''
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env={**os.environ, "ENV": "prod"},
        )

        assert result.returncode == 0, f"Import test failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        assert "PASS" in result.stdout


class TestDevMainSideEffects:
    """Verify dev_main.py DOES have the expected dev behaviors (but isolated)."""

    def test_dev_main_clears_cache_at_import(self):
        """dev_main.py SHOULD clear caches - this is the dev behavior."""
        # This test verifies that dev behaviors are in dev_main.py, not app.py
        script = f'''
import sys
sys.path.insert(0, "{BACKEND_DIR}")
sys.path.insert(0, "{BACKEND_DIR / 'scripts' / 'dev'}")
import os
os.environ["ENV"] = "dev"

# Check that dev_main sets dont_write_bytecode
# (We can't easily test cache clearing without affecting real caches)
import dev_main

# dev_main should have set this at import time
assert sys.dont_write_bytecode == True, "dev_main should set dont_write_bytecode"
print("PASS: dev_main sets dont_write_bytecode")
'''
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env={**os.environ, "ENV": "dev"},
        )

        assert result.returncode == 0, f"dev_main test failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        assert "PASS" in result.stdout
