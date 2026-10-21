"""Background ping daemon operations: start / stop / status."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from core.debug.context import DebugContext
from core.debug.ping import (
    ensure_background_ping,
    ping_status,
    stop_background_ping,
)
from core.debug.result import DebugResult


def run_ping_start(
    start: Path | None = None,
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
    **kwargs: Any,
) -> DebugResult:
    """Start background ``pingDebugUIParams`` keepalive (CLI between commands)."""
    ctx = DebugContext.open(start, config_id=config_id, runtime_id=runtime_id)
    if isinstance(ctx, DebugResult):
        return ctx
    return _with_identity(ctx, ensure_background_ping(ctx.root, **kwargs))


def run_ping_stop(
    start: Path | None = None,
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
    **kwargs: Any,
) -> DebugResult:
    ctx = DebugContext.open(start, config_id=config_id, runtime_id=runtime_id)
    if isinstance(ctx, DebugResult):
        return ctx
    return _with_identity(ctx, stop_background_ping(ctx.root, **kwargs))


def run_ping_status(
    start: Path | None = None,
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
    **kwargs: Any,
) -> DebugResult:
    ctx = DebugContext.open(start, config_id=config_id, runtime_id=runtime_id)
    if isinstance(ctx, DebugResult):
        return ctx
    return _with_identity(ctx, ping_status(ctx.root, **kwargs))


def _with_identity(ctx: DebugContext, result: DebugResult) -> DebugResult:
    result.duration = time.perf_counter() - ctx.started
    result.config_id = ctx.config_id
    result.runtime_id = ctx.runtime_id
    return result
