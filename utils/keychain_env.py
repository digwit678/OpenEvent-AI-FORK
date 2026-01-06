from __future__ import annotations

import os
import subprocess
import sys
from typing import Dict, Optional, Tuple

_KEYCHAIN_ITEMS = {
    "OPENAI_API_KEY": ("openevent-api-test-key", True),
    "GOOGLE_API_KEY": ("openevent-gemini-key", False),
}


_TRUTHY = {"1", "true", "yes", "on"}


def _is_truthy(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in _TRUTHY


def _read_keychain(service: str, *, account: Optional[str]) -> Optional[str]:
    if sys.platform != "darwin":
        return None

    if account:
        cmd = ["security", "find-generic-password", "-a", account, "-s", service, "-w"]
    else:
        cmd = ["security", "find-generic-password", "-s", service, "-w"]

    try:
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    except FileNotFoundError:
        return None

    if result.returncode != 0:
        return None
    return (result.stdout or "").strip() or None


def load_keychain_env() -> Dict[str, str]:
    """Populate missing API key env vars from macOS Keychain (does not override env)."""
    if sys.platform != "darwin":
        return {}
    if _is_truthy(os.getenv("OE_DISABLE_KEYCHAIN_ENV")):
        return {}

    loaded: Dict[str, str] = {}
    for env_var, (service, use_account) in _KEYCHAIN_ITEMS.items():
        if os.getenv(env_var):
            continue
        account = os.getenv("USER") if use_account else None
        value = (
            _read_keychain(service, account=account)
            or _read_keychain(service, account=None)
            or _read_keychain(env_var, account=account)
            or _read_keychain(env_var, account=None)
        )
        if value:
            os.environ[env_var] = value
            loaded[env_var] = "<loaded>"
    return loaded
