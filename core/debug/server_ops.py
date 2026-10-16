"""dbgs server operations: start / stop / status (ADR-031 / #140)."""

from __future__ import annotations

from pathlib import Path

from adapters.debug_http import (
    TransportFn,
)
from adapters.platform_1cv8 import IsRunningFn, TerminateFn
from core.debug.common import resolve_debug_password
from core.debug.context import DebugContext
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
    ctx = DebugContext.open(
        start, config_id=config_id, runtime_id=runtime_id, transport=transport
    )
    if isinstance(ctx, DebugResult):
        return ctx
    pwd = resolve_debug_password(password)
    return server_start(
        ctx.root,
        ctx.data,
        started=ctx.started,
        host=host,
        port=port,
        password=pwd or None,
        config_id=ctx.config_id,
        runtime_id=ctx.runtime_id,
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
    ctx = DebugContext.open(start, config_id=config_id, runtime_id=runtime_id)
    if isinstance(ctx, DebugResult):
        return ctx
    stop_background_ping(ctx.root, is_alive=is_alive, terminate_fn=terminate_fn)
    return server_stop(
        ctx.root,
        started=ctx.started,
        config_id=ctx.config_id,
        runtime_id=ctx.runtime_id,
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
    ctx = DebugContext.open(
        start, config_id=config_id, runtime_id=runtime_id, transport=transport
    )
    if isinstance(ctx, DebugResult):
        return ctx
    return server_status(
        ctx.root,
        started=ctx.started,
        config_id=ctx.config_id,
        runtime_id=ctx.runtime_id,
        is_alive=is_alive,
        transport=transport,
    )
