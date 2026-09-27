"""1cv8 platform adapter: launch thick client against file IB (ADR-019)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from adapters.platform_1cv8.process import (
    build_enterprise_argv,
    is_running,
    spawn_detached,
    terminate,
)

SpawnFn = Callable[[Sequence[str]], int]
IsRunningFn = Callable[[int], bool]
TerminateFn = Callable[[int], bool]


def start_enterprise_client(
    onecv8: Path,
    *,
    ib_path: Path,
    debug: bool = False,
    spawn: SpawnFn | None = None,
    settle_seconds: float = 0.3,
    is_alive: IsRunningFn | None = None,
) -> tuple[int, list[str]]:
    """
    Detach-start ENTERPRISE client.

    Returns (pid, argv). Raises RuntimeError if process exits immediately.
    """
    import time

    argv = build_enterprise_argv(onecv8, ib_path=ib_path, debug=debug)
    spawner = spawn or spawn_detached
    alive = is_alive or is_running
    pid = spawner(argv)
    if settle_seconds > 0:
        time.sleep(settle_seconds)
    if not alive(pid):
        raise RuntimeError("1cv8 завершился сразу после запуска")
    return pid, argv


def stop_client(
    pid: int,
    *,
    terminate_fn: TerminateFn | None = None,
) -> bool:
    """Terminate client process; return True if no longer running."""
    stopper = terminate_fn or (lambda p: terminate(p))
    return stopper(pid)


__all__ = [
    "IsRunningFn",
    "SpawnFn",
    "TerminateFn",
    "build_enterprise_argv",
    "is_running",
    "spawn_detached",
    "start_enterprise_client",
    "stop_client",
    "terminate",
]
