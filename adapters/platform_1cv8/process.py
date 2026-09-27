"""Cross-platform process helpers for detached 1cv8 client (ADR-019)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path


def is_running(pid: int) -> bool:
    """Return True if a process with the given pid appears alive."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _win_is_running(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def terminate(pid: int, *, timeout: float = 5.0) -> bool:
    """
    Ask the process to exit; escalate if needed.

    Returns True if the process is no longer running afterwards.
    """
    if pid <= 0:
        return True
    if not is_running(pid):
        return True
    if sys.platform == "win32":
        return _win_terminate(pid, timeout=timeout)
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_running(pid):
            return True
        time.sleep(0.05)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    time.sleep(0.05)
    return not is_running(pid)


def spawn_detached(argv: Sequence[str]) -> int:
    """Start process detached from this session; return pid."""
    args = list(argv)
    if sys.platform == "win32":
        # CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS
        creationflags = 0x00000200 | 0x00000008
        proc = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creationflags,
        )
    else:
        proc = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
    return int(proc.pid)


def build_enterprise_argv(
    onecv8: Path,
    *,
    ib_path: Path,
    debug: bool = False,
) -> list[str]:
    """Build argv for thick client ENTERPRISE against a file IB."""
    argv = [
        str(onecv8),
        "ENTERPRISE",
        f"/F{ib_path.resolve()}",
    ]
    if debug:
        argv.append("/Debug")
    return argv


def _win_is_running(pid: int) -> bool:
    import ctypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    process_query_limited_information = 0x1000
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if handle:
        kernel32.CloseHandle(handle)
        return True
    return False


def _win_terminate(pid: int, *, timeout: float) -> bool:
    import ctypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    process_terminate = 0x0001
    synchronize = 0x00100000
    handle = kernel32.OpenProcess(process_terminate | synchronize, False, pid)
    if not handle:
        return not is_running(pid)
    try:
        if not kernel32.TerminateProcess(handle, 1):
            return False
        wait_ms = max(1, int(timeout * 1000))
        kernel32.WaitForSingleObject(handle, wait_ms)
    finally:
        kernel32.CloseHandle(handle)
    return not is_running(pid)
