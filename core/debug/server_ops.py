"""dbgs server operations: start / stop / status (ADR-031 / #140)."""

from __future__ import annotations

import os
import time
from pathlib import Path

from adapters.debug_http import (
    TransportFn,
)
from adapters.platform_1cv8 import IsRunningFn, TerminateFn
from core.debug.common import (
    load_project,
)
from core.debug.ping import (
    stop_background_ping,
)
from core.debug.result import DebugResult
from core.debug.server import (
    DiscoverFn,
    SpawnDbgsFn,
    server_start,
    server_status,
    server_stop,
)


def run_server_start(
    start: Path | None = None,
    *,
    host: str | None = None,
    port: int | None = None,
    password: str | None = None,
    config_id: str | None = None,
    runtime_id: str | None = None,
    discover: DiscoverFn | None = None,
    spawn: SpawnDbgsFn | None = None,
    is_alive: IsRunningFn | None = None,
    transport: TransportFn | None = None,
    settle_seconds: float = 0.1,
    notify_timeout: float = 5.0,
) -> DebugResult:
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    root, data, target, err = load_project(
        start_path, started=started, config_id=config_id, runtime_id=runtime_id
    )
    if err is not None:
        return err
    assert target is not None
    pwd = password if password is not None else os.environ.get("ONEC_DEBUG_PASSWORD")
    return server_start(
        root,
        data,
        started=started,
        host=host,
        port=port,
        password=pwd or None,
        config_id=target.config_id,
        runtime_id=target.runtime_id,
        discover=discover,
        spawn=spawn,
        is_alive=is_alive,
        transport=transport,
        settle_seconds=settle_seconds,
        notify_timeout=notify_timeout,
    )


def run_server_stop(
    start: Path | None = None,
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
    is_alive: IsRunningFn | None = None,
    terminate_fn: TerminateFn | None = None,
) -> DebugResult:
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    root, _data, target, err = load_project(
        start_path, started=started, config_id=config_id, runtime_id=runtime_id
    )
    if err is not None:
        return err
    assert target is not None
    stop_background_ping(root, is_alive=is_alive, terminate_fn=terminate_fn)
    return server_stop(
        root,
        started=started,
        config_id=target.config_id,
        runtime_id=target.runtime_id,
        is_alive=is_alive,
        terminate_fn=terminate_fn,
    )


def run_server_status(
    start: Path | None = None,
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
    is_alive: IsRunningFn | None = None,
    transport: TransportFn | None = None,
) -> DebugResult:
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    root, _data, target, err = load_project(
        start_path, started=started, config_id=config_id, runtime_id=runtime_id
    )
    if err is not None:
        return err
    assert target is not None
    return server_status(
        root,
        started=started,
        config_id=target.config_id,
        runtime_id=target.runtime_id,
        is_alive=is_alive,
        transport=transport,
    )
