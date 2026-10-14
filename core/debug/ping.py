"""Background ``pingDebugUIParams`` keepalive between short-lived CLI processes.

ADR-031 keeps in-process ping for MCP (stdio holds the process). CLI commands exit
immediately after each call; without a helper the platform releases a stopped
target within seconds. This module spawns ``python -m core.debug.ping_worker``.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from adapters.platform_1cv8 import IsRunningFn, TerminateFn, is_running, terminate
from core.debug.constants import (
    CODE_NO_SESSION,
    PING_LOG_NAME,
    SOURCE_DEBUG,
)
from core.debug.result import DebugResult, exit_code_for_result
from core.debug.state import (
    alive_ping,
    clear_ping_state,
    read_session,
    state_dir,
    write_ping_state,
)
from core.diagnostics import error, warning
from core.exit_codes import SUCCESS

SpawnPingFn = Callable[[Path, Path], int]


def ping_log_path(root: Path) -> Path:
    return state_dir(root) / PING_LOG_NAME


def default_spawn_ping(root: Path, log_path: Path) -> int:
    """Detach-start keepalive worker; return pid."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = open(log_path, "ab")  # noqa: SIM115 — lives with process
    env = os.environ.copy()
    # Source checkout: ensure repo root is importable when launched via sys.executable.
    repo_hint = str(Path(__file__).resolve().parents[2])
    existing = env.get("PYTHONPATH", "")
    if repo_hint not in existing.split(os.pathsep):
        env["PYTHONPATH"] = (
            repo_hint if not existing else f"{repo_hint}{os.pathsep}{existing}"
        )
    # Fast interval: CLI step-in/continue poll lastStop written by this worker;
    # 500ms default left gaps that felt like hangs after StepIn.
    from adapters.debug_http.constants import ARM_PING_INTERVAL_SEC

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "core.debug.ping_worker",
            "--root",
            str(root.resolve()),
            "--interval",
            str(ARM_PING_INTERVAL_SEC),
        ],
        stdout=log,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        close_fds=True,
        start_new_session=True,
        env=env,
        cwd=str(root.resolve()),
    )
    return int(proc.pid)


def ensure_background_ping(
    root: Path,
    *,
    spawn: SpawnPingFn | None = None,
    is_alive: IsRunningFn | None = None,
) -> DebugResult:
    """Idempotent start of keepalive if ``session.json`` exists."""
    started = time.perf_counter()
    running, pid, meta = alive_ping(root, is_alive=is_alive)
    stored = read_session(root)
    if stored is None:
        diags = [
            error(
                "нет активной debug-сессии для ping",
                code=CODE_NO_SESSION,
                source=SOURCE_DEBUG,
                suggestion="сначала debug attach / runtime start --debug",
            )
        ]
        return DebugResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            ping_running=False,
            diagnostics=diags,
            exit_code=exit_code_for_result("failed", diags),
        )
    session_id = str(stored.get("sessionId") or "")
    url = str(stored.get("url") or "")
    if running and pid is not None:
        meta_sid = str(meta.get("sessionId") or "")
        if not (meta_sid and session_id and meta_sid != session_id):
            return DebugResult(
                status="ok",
                duration=time.perf_counter() - started,
                root=root,
                url=url or None,
                session_id=session_id or None,
                ping_pid=pid,
                ping_running=True,
                exit_code=SUCCESS,
            )
        # Session reattached — recycle keepalive for the new sessionId.
        stop_background_ping(root, is_alive=is_alive)

    spawner = spawn or default_spawn_ping
    try:
        new_pid = spawner(root, ping_log_path(root))
    except OSError as exc:
        diags = [
            warning(
                f"не удалось запустить background ping: {exc}",
                code=CODE_NO_SESSION,
                source=SOURCE_DEBUG,
                suggestion="между CLI-командами стоп может отпуститься без keepalive",
            )
        ]
        return DebugResult(
            status="ok",
            duration=time.perf_counter() - started,
            root=root,
            url=url or None,
            session_id=session_id or None,
            ping_running=False,
            diagnostics=diags,
            exit_code=SUCCESS,
        )
    write_ping_state(root, pid=new_pid, session_id=session_id, url=url)
    return DebugResult(
        status="ok",
        duration=time.perf_counter() - started,
        root=root,
        url=url or None,
        session_id=session_id or None,
        ping_pid=new_pid,
        ping_running=True,
        exit_code=SUCCESS,
    )


def stop_background_ping(
    root: Path,
    *,
    is_alive: IsRunningFn | None = None,
    terminate_fn: TerminateFn | None = None,
) -> DebugResult:
    """Stop keepalive helper; clear ``ping.pid`` even if already dead."""
    started = time.perf_counter()
    running, pid, _meta = alive_ping(root, is_alive=is_alive)
    if not running or pid is None:
        clear_ping_state(root)
        return DebugResult(
            status="ok",
            duration=time.perf_counter() - started,
            root=root,
            ping_running=False,
            exit_code=SUCCESS,
        )
    stopper: Callable[..., bool] = terminate_fn or terminate
    alive = is_alive or is_running
    # Short timeout: a multi-second wait here is a keepalive gap (target resumes).
    try:
        ok = stopper(pid, timeout=0.5)
    except TypeError:
        ok = stopper(pid)
    if alive(pid) and not ok:
        diags = [
            error(
                f"не удалось остановить ping pid={pid}",
                code=CODE_NO_SESSION,
                source=SOURCE_DEBUG,
            )
        ]
        return DebugResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            ping_pid=pid,
            ping_running=True,
            diagnostics=diags,
            exit_code=exit_code_for_result("failed", diags),
        )
    clear_ping_state(root)
    return DebugResult(
        status="ok",
        duration=time.perf_counter() - started,
        root=root,
        ping_pid=pid,
        ping_running=False,
        exit_code=SUCCESS,
    )


def ping_status(
    root: Path,
    *,
    is_alive: IsRunningFn | None = None,
) -> DebugResult:
    started = time.perf_counter()
    running, pid, meta = alive_ping(root, is_alive=is_alive)
    stored = read_session(root)
    return DebugResult(
        status="ok",
        duration=time.perf_counter() - started,
        root=root,
        url=(
            str(meta.get("url") or "")
            or (str(stored.get("url") or "") if stored else "")
            or None
        ),
        session_id=(
            str(meta.get("sessionId") or "")
            or (str(stored.get("sessionId") or "") if stored else "")
            or None
        ),
        ping_pid=pid,
        ping_running=running,
        attached=stored is not None,
        exit_code=SUCCESS,
    )


def soft_ensure_background_ping(root: Path, **kwargs: Any) -> list[Any]:
    """Best-effort ensure; never fails the parent command — returns diagnostics."""
    try:
        result = ensure_background_ping(root, **kwargs)
    except Exception as exc:  # noqa: BLE001 — keepalive must not break wait/attach
        return [
            warning(
                f"background ping: {exc}",
                code=CODE_NO_SESSION,
                source=SOURCE_DEBUG,
            )
        ]
    return list(result.diagnostics)
