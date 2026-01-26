#!/usr/bin/env python3
"""
Development-only startup script with auto-launch behaviors.

This script handles dev conveniences that should NEVER run in production:
- Bytecode cache clearing (prevents stale .pyc issues)
- Frontend auto-launch
- Browser auto-open
- Port cleanup

For production deployment, use: uvicorn app:app
For development, use: python scripts/dev/dev_main.py
"""
import sys
import os
import shutil
import importlib
import signal
import socket
import subprocess
import threading
import time
import webbrowser
import atexit
from pathlib import Path
from typing import List, Optional

# Ensure we're in the backend directory for imports
BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# ============================================================
# DEV-ONLY: Clear bytecode caches BEFORE any other imports
# ============================================================
sys.dont_write_bytecode = True  # Prevent new cache writes

def _clear_pycache() -> int:
    """Clear all __pycache__ directories. Returns count of cleared directories."""
    cleared = 0
    for cache_dir in BACKEND_DIR.rglob("__pycache__"):
        try:
            shutil.rmtree(cache_dir)
            cleared += 1
        except Exception:
            pass
    return cleared

# Clear caches immediately at import time (before app import)
_cleared = _clear_pycache()
importlib.invalidate_caches()

# ============================================================
# DEV-ONLY: Environment setup
# ============================================================
# Force dev mode
os.environ.setdefault("ENV", "dev")

# Smart default for AGENT_MODE
if not os.getenv("AGENT_MODE"):
    has_gemini = os.getenv("GOOGLE_API_KEY") or os.getenv("gemini_key_openevent")
    if not has_gemini:
        os.environ["AGENT_MODE"] = "openai"

# Now safe to import the app
from app import app, logger

# Dev security warning
print("[SECURITY] Running in DEVELOPMENT mode - debug endpoints exposed")
print("[SECURITY] Set ENV=prod for production deployments")

if _cleared:
    logger.info("[Dev] Cleared %d __pycache__ directories at startup", _cleared)

# ============================================================
# Configuration
# ============================================================
FRONTEND_DIR = BACKEND_DIR.parent / "atelier-ai-frontend"
FRONTEND_PORT = int(os.getenv("FRONTEND_PORT", "3000"))
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))
BACKEND_HOST = os.getenv("BACKEND_HOST", "0.0.0.0")
DEV_DIR = BACKEND_DIR.parent / ".dev"

_frontend_process: Optional[subprocess.Popen] = None


# ============================================================
# Port management utilities
# ============================================================
def _is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    else:
        return True


def _pids_listening_on_tcp_port(port: int) -> List[int]:
    """Return PIDs listening on localhost TCP port (best effort; macOS/Linux)."""
    if not shutil.which("lsof"):
        return []
    try:
        output = subprocess.check_output(
            ["lsof", "-nP", f"-tiTCP:{port}", "-sTCP:LISTEN"],
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return []
    pids: List[int] = []
    for line in output.decode().splitlines():
        value = line.strip()
        if not value:
            continue
        try:
            pids.append(int(value))
        except ValueError:
            continue
    return sorted(set(pids))


def _terminate_pid(pid: int, timeout_s: float = 3.0) -> None:
    """Terminate a pid (TERM then KILL), best effort."""
    if pid <= 0 or pid == os.getpid():
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not _pid_exists(pid):
            return
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        return


def _ensure_backend_port_free(port: int) -> None:
    if not _is_port_in_use(port):
        return
    if os.getenv("AUTO_FREE_BACKEND_PORT", "1") != "1":
        raise RuntimeError(
            f"Port {port} is already in use. Stop the existing process or set AUTO_FREE_BACKEND_PORT=1."
        )
    pids = _pids_listening_on_tcp_port(port)
    if not pids:
        raise RuntimeError(
            f"Port {port} is already in use, but no PID could be discovered (missing lsof?)."
        )
    logger.warning("[Backend] Port %s is in use; terminating listeners: %s", port, ', '.join(map(str, pids)))
    for pid in pids:
        _terminate_pid(pid)
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if not _is_port_in_use(port):
            return
        time.sleep(0.1)
    remaining = _pids_listening_on_tcp_port(port)
    raise RuntimeError(
        f"Port {port} is still in use after attempting cleanup (remaining PIDs: {remaining or 'unknown'})."
    )


# ============================================================
# PID file management
# ============================================================
def _write_pidfile(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{os.getpid()}\n", encoding="utf-8")
    except Exception as exc:
        logger.warning("[Backend] Failed to write pidfile %s: %s", path, exc)


def _cleanup_pidfile(path: Path) -> None:
    try:
        if not path.exists():
            return
        existing = path.read_text(encoding="utf-8").strip()
        if existing and existing != str(os.getpid()):
            return
        path.unlink(missing_ok=True)
    except Exception:
        return


# ============================================================
# Frontend management
# ============================================================
def _is_frontend_healthy(port: int, timeout: float = 2.0) -> bool:
    """Check if frontend returns a healthy response (not 500 error)."""
    import urllib.request
    import urllib.error
    try:
        req = urllib.request.Request(f"http://localhost:{port}/", method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status < 500
    except urllib.error.HTTPError as e:
        return e.code < 500
    except Exception:
        return False


def _kill_unhealthy_frontend() -> None:
    """Kill any existing frontend processes and clear cache."""
    logger.info("[Frontend] Killing unhealthy frontend and clearing cache...")
    subprocess.run(["pkill", "-f", "next dev"], capture_output=True)
    time.sleep(0.5)
    next_cache = FRONTEND_DIR / ".next"
    if next_cache.exists():
        try:
            shutil.rmtree(next_cache)
            logger.info("[Frontend] Cleared .next cache")
        except Exception as e:
            logger.warning("[Frontend] Could not clear .next cache: %s", e)
    time.sleep(0.5)


def _launch_frontend() -> Optional[subprocess.Popen]:
    if os.getenv("AUTO_LAUNCH_FRONTEND", "1") != "1":
        return None

    frontend_pidfile = DEV_DIR / "frontend.pid"
    try:
        if frontend_pidfile.exists():
            existing = frontend_pidfile.read_text(encoding="utf-8").strip()
            existing_pid = int(existing) if existing else None
            if (
                existing_pid
                and _pid_exists(existing_pid)
                and _is_port_in_use(FRONTEND_PORT)
                and _is_frontend_healthy(FRONTEND_PORT)
            ):
                logger.info("[Frontend] Reusing existing frontend process (pid=%s) on http://localhost:%s",
                           existing_pid, FRONTEND_PORT)
                return None
            frontend_pidfile.unlink(missing_ok=True)
    except Exception:
        pass

    if _is_port_in_use(FRONTEND_PORT):
        if _is_frontend_healthy(FRONTEND_PORT):
            logger.info("[Frontend] Port %s already in use - frontend is healthy.", FRONTEND_PORT)
            return None
        else:
            logger.warning("[Frontend] Port %s in use but returning errors!", FRONTEND_PORT)
            if os.getenv("AUTO_FIX_FRONTEND", "1") == "1":
                _kill_unhealthy_frontend()
            else:
                logger.warning("[Frontend] Set AUTO_FIX_FRONTEND=1 to auto-fix, or run:")
                logger.warning("[Frontend]   pkill -f 'next dev' && rm -rf atelier-ai-frontend/.next")
                return None

    if not FRONTEND_DIR.exists():
        logger.warning("[Frontend] Directory %s not found; skipping auto-launch.", FRONTEND_DIR)
        return None
    if not (FRONTEND_DIR / "package.json").exists():
        logger.warning("[Frontend] No package.json in %s; skipping auto-launch.", FRONTEND_DIR)
        return None

    cmd = ["npm", "run", "dev", "--", "--hostname", "0.0.0.0", "--port", str(FRONTEND_PORT)]
    try:
        env = os.environ.copy()
        env.setdefault("NEXT_PUBLIC_BACKEND_BASE", f"http://localhost:{BACKEND_PORT}")
        proc = subprocess.Popen(cmd, cwd=str(FRONTEND_DIR), env=env, start_new_session=True)
        try:
            DEV_DIR.mkdir(parents=True, exist_ok=True)
            frontend_pidfile.write_text(f"{proc.pid}\n", encoding="utf-8")
        except Exception:
            pass
        logger.info("[Frontend] npm dev server starting on http://localhost:%s", FRONTEND_PORT)
        return proc
    except FileNotFoundError:
        logger.warning("[Frontend] npm not found on PATH; skipping auto-launch.")
    except Exception as exc:
        logger.error("[Frontend] Failed to launch npm dev server: %s", exc)
    return None


def _open_browser_when_ready() -> None:
    if os.getenv("AUTO_OPEN_FRONTEND", "1") != "1":
        return
    target_url = f"http://localhost:{FRONTEND_PORT}"
    debug_url = f"{target_url}/debug"
    for attempt in range(120):
        if _is_port_in_use(FRONTEND_PORT):
            try:
                webbrowser.open_new(target_url)
                if os.getenv("AUTO_OPEN_DEBUG_PANEL", "1") == "1":
                    webbrowser.open_new_tab(debug_url)
            except Exception as exc:
                logger.warning("[Frontend] Unable to open browser automatically: %s", exc)
            else:
                logger.info("[Frontend] Opened browser window at %s", target_url)
                if os.getenv("AUTO_OPEN_DEBUG_PANEL", "1") == "1":
                    logger.info("[Frontend] Opened debug panel at %s", debug_url)
            return
        time.sleep(0.5)
    logger.warning("[Frontend] Frontend not reachable on %s after waiting 60s; skipping auto-open.", target_url)


def _stop_frontend_process() -> None:
    global _frontend_process
    proc = _frontend_process
    if not proc:
        return
    try:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except Exception:
                proc.terminate()
            proc.wait(timeout=5)
    except Exception:
        try:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                proc.kill()
        except Exception:
            pass
    finally:
        try:
            pidfile = DEV_DIR / "frontend.pid"
            if pidfile.exists() and pidfile.read_text(encoding="utf-8").strip() == str(proc.pid):
                pidfile.unlink(missing_ok=True)
        except Exception:
            pass
        _frontend_process = None


# ============================================================
# Debug trace persistence
# ============================================================
def _persist_debug_reports() -> None:
    from debug.settings import is_trace_enabled
    if not is_trace_enabled():
        return
    try:
        from debug.trace import BUS
        from api.debug import debug_generate_report
        thread_ids = BUS.list_threads()
    except Exception as exc:
        logger.warning("[Debug] Unable to enumerate trace threads: %s", exc)
        return
    for thread_id in thread_ids:
        try:
            debug_generate_report(thread_id, persist=True)
        except Exception as exc:
            logger.warning("[Debug] Failed to persist debug report for %s: %s", thread_id, exc)


# ============================================================
# Main entry point
# ============================================================
def main():
    global _frontend_process
    import uvicorn

    logger.info("[Backend] Starting in DEV mode (ENV=%s)", os.getenv("ENV", "dev"))

    # Clear caches again (in case of long-running process)
    cleared = _clear_pycache()
    if cleared:
        logger.info("[Backend] Cleared %d __pycache__ directories", cleared)

    # PID file management
    backend_pidfile = DEV_DIR / "backend.pid"
    _write_pidfile(backend_pidfile)
    atexit.register(_cleanup_pidfile, backend_pidfile)

    # Port management
    _ensure_backend_port_free(BACKEND_PORT)

    # Frontend management
    _frontend_process = _launch_frontend()
    threading.Thread(target=_open_browser_when_ready, name="frontend-browser", daemon=True).start()

    # Debug trace persistence on exit
    if os.getenv("DEBUG_TRACE_PERSIST_ON_EXIT", "0") == "1":
        atexit.register(_persist_debug_reports)
    atexit.register(_stop_frontend_process)

    try:
        uvicorn.run(app, host=BACKEND_HOST, port=BACKEND_PORT)
    finally:
        _stop_frontend_process()


if __name__ == "__main__":
    main()
