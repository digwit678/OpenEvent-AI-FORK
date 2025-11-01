"""Utility helpers for checking and freeing TCP ports during development."""

from __future__ import annotations

import contextlib
import os
import signal
import socket
import subprocess
from typing import Iterable, Optional


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def first_free_port(candidates: Iterable[int]) -> Optional[int]:
    for port in candidates:
        if not is_port_in_use(port):
            return port
    return None


def kill_port_process(port: int) -> None:
    """Terminate any process listening on ``port`` (best effort)."""

    try:
        import psutil  # type: ignore

        for proc in psutil.process_iter(["pid", "connections"]):
            for conn in proc.connections():
                if conn.laddr and conn.laddr.port == port:
                    try:
                        proc.terminate()
                        proc.wait(timeout=3)
                    except Exception:
                        proc.kill()
                    break
    except ImportError:
        _kill_with_lsof(port)


def _kill_with_lsof(port: int) -> None:
    if not shutil.which("lsof"):
        return
    try:
        output = subprocess.check_output(["lsof", "-ti", f"tcp:{port}"])  # nosec B603
    except subprocess.CalledProcessError:
        return
    pids = {pid for pid in output.decode().strip().splitlines() if pid}
    for pid in pids:
        try:
            os.kill(int(pid), signal.SIGTERM)
        except OSError:
            continue


import shutil  # noqa: E402  (placed after psutil logic to avoid unnecessary import)

