"""Debug ↔ runtime integration: boot before spawn, arm targets, teardown."""

from __future__ import annotations

import shutil
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from adapters.debug_http import (
    DebugHttpError,
    TransportFn,
)
from adapters.platform_1cv8 import IsRunningFn, TerminateFn
from core.debug.breakpoints import parse_breakpoint_specs, run_breakpoint_set
from core.debug.common import (
    SessionFactory,
)
from core.debug.constants import (
    CODE_DBGS_UNREACHABLE,
    CODE_NO_SESSION,
    SOURCE_DEBUG,
)
from core.debug.context import DebugContext
from core.debug.ping import (
    soft_ensure_background_ping,
    stop_background_ping,
)
from core.debug.result import DebugResult
from core.debug.server import (
    DiscoverFn,
    SpawnDbgsFn,
    server_stop,
)
from core.debug.server_ops import run_server_start
from core.debug.session_ops import run_attach
from core.debug.state import (
    clear_session,
    eval_dir,
    ping_pid_path,
    read_server_pid,
    read_session,
    reset_session_runtime,
    resolve_debugger_url,
    server_pid_path,
    session_lock_path,
    session_path,
)
from core.diagnostics import Diagnostic, error, warning


def ensure_debug_for_runtime(
    start: Path | None = None,
    *,
    breakpoints: Sequence[str] | None = None,
    debugger_url: str | None = None,
    config_id: str | None = None,
    runtime_id: str | None = None,
    discover: DiscoverFn | None = None,
    spawn: SpawnDbgsFn | None = None,
    is_alive: IsRunningFn | None = None,
    transport: TransportFn | None = None,
    session_factory: SessionFactory | None = None,
) -> DebugResult:
    """Ensure dbgs + attach + optional file BPs before ``runtime start --debug --bp``.

    Idempotent server start; attach if no session; set breakpoints by ``--file``.
    Does not start the 1C client — caller runs ``runtime.start`` then sync targets.
    """
    ctx = DebugContext.open(
        start,
        config_id=config_id,
        runtime_id=runtime_id,
        transport=transport,
        session_factory=session_factory,
    )
    if isinstance(ctx, DebugResult):
        return ctx
    specs, parse_diags = parse_breakpoint_specs(list(breakpoints or []))
    if parse_diags:
        return ctx.fail(parse_diags)

    server = run_server_start(
        ctx.start,
        config_id=config_id,
        runtime_id=runtime_id,
        discover=discover,
        spawn=spawn,
        is_alive=is_alive,
        transport=transport,
    )
    if server.status != "ok":
        server.duration = time.perf_counter() - ctx.started
        return server

    need_attach = read_session(ctx.root) is None
    if not need_attach:
        # Session already on disk — validate that it can be restored for BP set.
        restored = ctx.restore()
        if isinstance(restored, DebugResult):
            need_attach = True
        else:
            soft_ensure_background_ping(ctx.root)
    if need_attach:
        attached = run_attach(
            ctx.start,
            url=debugger_url or server.url,
            config_id=config_id,
            runtime_id=runtime_id,
            transport=transport,
            session_factory=session_factory,
        )
        if attached.status != "ok":
            attached.duration = time.perf_counter() - ctx.started
            return attached

    bp_out: list[dict[str, Any]] = []
    for spec in specs:
        set_result = run_breakpoint_set(
            ctx.start,
            file=spec.file,
            lines=spec.lines,
            config_id=config_id,
            runtime_id=runtime_id,
            transport=transport,
            session_factory=session_factory,
        )
        if set_result.status != "ok":
            set_result.duration = time.perf_counter() - ctx.started
            return set_result
        bp_out.extend(set_result.breakpoints)

    base = (
        debugger_url
        or server.url
        or resolve_debugger_url(ctx.root, ctx.data, explicit=debugger_url)
    )
    session_meta = read_session(ctx.root) or {}
    return ctx.ok(
        url=base,
        alias=str(session_meta.get("alias") or "") or None,
        session_id=str(session_meta.get("sessionId") or "") or None,
        attached=True,
        debugger_url=base,
        breakpoints=bp_out,
        host=server.host,
        port=server.port,
        pid=server.pid,
        running=server.running,
    )


def prepare_debug_for_spawn(
    start: Path | None = None,
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
    **ping_kwargs: Any,
) -> DebugResult:
    """Drop stale stop/targets and make sure the daemon runs — call before spawn.

    Without the reset ``debug wait`` would return the stop of the previous client.
    """
    ctx = DebugContext.open(start, config_id=config_id, runtime_id=runtime_id)
    if isinstance(ctx, DebugResult):
        return ctx
    if read_session(ctx.root) is None:
        return ctx.fail(
            [
                error(
                    "нет активной debug-сессии",
                    code=CODE_NO_SESSION,
                    source=SOURCE_DEBUG,
                    suggestion="выполните 1c-dev debug attach",
                )
            ]
        )
    reset_session_runtime(ctx.root)
    diags = soft_ensure_background_ping(ctx.root, **ping_kwargs)
    return ctx.ok(attached=True, diagnostics=diags)

def await_debug_targets_armed(
    start: Path | None = None,
    *,
    timeout: float = 15.0,
    poll_interval: float = 0.1,
    config_id: str | None = None,
    runtime_id: str | None = None,
    transport: TransportFn | None = None,
    session_factory: SessionFactory | None = None,
) -> DebugResult:
    """Poll ``session.json`` until the daemon has attached a target (or timeout).

    Read-only: the ping daemon owns attach + breakpoint re-arm; this never talks
    to dbgs, so it cannot steal ping events.
    """
    del transport, session_factory  # kept for API compatibility
    ctx = DebugContext.open(start, config_id=config_id, runtime_id=runtime_id)
    if isinstance(ctx, DebugResult):
        return ctx
    ping_diags = soft_ensure_background_ping(ctx.root)
    deadline = ctx.started + max(0.0, timeout)
    targets: list[str] = []
    while True:
        stored = read_session(ctx.root)
        if stored is None:
            return ctx.fail(
                [
                    error(
                        "нет активной debug-сессии",
                        code=CODE_NO_SESSION,
                        source=SOURCE_DEBUG,
                        suggestion="выполните 1c-dev debug attach",
                    )
                ]
            )
        raw = stored.get("attachedTargets")
        targets = [str(t) for t in raw if isinstance(t, str) and t] if isinstance(raw, list) else []
        if targets or time.perf_counter() >= deadline:
            break
        time.sleep(max(0.02, poll_interval))
    base = str(stored.get("url") or "") or resolve_debugger_url(ctx.root, ctx.data)
    return ctx.ok(
        url=base or None,
        alias=str(stored.get("alias") or "") or None,
        session_id=str(stored.get("sessionId") or "") or None,
        attached=True,
        targets=[{"targetId": t} for t in targets],
        diagnostics=ping_diags,
    )

def sync_debug_targets_after_runtime(
    start: Path | None = None,
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
    transport: TransportFn | None = None,
    session_factory: SessionFactory | None = None,
) -> DebugResult:
    """Compat alias: targets are armed by the daemon; wait for it."""
    return await_debug_targets_armed(
        start,
        timeout=0.0,
        config_id=config_id,
        runtime_id=runtime_id,
        transport=transport,
        session_factory=session_factory,
    )


def has_debug_state(root: Path) -> bool:
    """True if ``.1c-dev/debug`` holds anything teardown should clean."""
    return any(
        path.exists()
        for path in (
            session_path(root),
            ping_pid_path(root),
            server_pid_path(root),
        )
    )


def teardown_debug(
    start: Path | None = None,
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
    transport: TransportFn | None = None,
    session_factory: SessionFactory | None = None,
    is_alive: IsRunningFn | None = None,
    terminate_fn: TerminateFn | None = None,
) -> DebugResult:
    """Stop everything debug-related: ping daemon, UI session, our own dbgs.

    Best effort and idempotent — failures become warnings so ``runtime stop``
    still reports the client state. ``dbgs`` is stopped only when we started it
    (``server.pid`` exists); an externally managed dbgs is left alone.
    """
    ctx = DebugContext.open(
        start,
        config_id=config_id,
        runtime_id=runtime_id,
        transport=transport,
        session_factory=session_factory,
    )
    if isinstance(ctx, DebugResult):
        return ctx
    root = ctx.root
    diags: list[Diagnostic] = []

    ping = stop_background_ping(root, is_alive=is_alive, terminate_fn=terminate_fn)
    if ping.status != "ok":
        diags.extend(_as_warnings(ping.diagnostics))

    if read_session(root) is not None:
        restored = ctx.restore()
        if not isinstance(restored, DebugResult):
            try:
                restored.session.force_detach()
            except DebugHttpError as exc:
                diags.extend(_as_warnings(exc.diagnostics))
            except Exception as exc:  # noqa: BLE001 — teardown must not raise
                diags.append(
                    warning(
                        f"debug detach: {exc}",
                        code=CODE_DBGS_UNREACHABLE,
                        source=SOURCE_DEBUG,
                    )
                )
        clear_session(root)
    try:
        session_lock_path(root).unlink(missing_ok=True)
        shutil.rmtree(eval_dir(root), ignore_errors=True)
    except OSError:
        pass

    server_running = False
    if read_server_pid(root) is not None:
        stopped = server_stop(
            root,
            started=ctx.started,
            config_id=ctx.config_id,
            runtime_id=ctx.runtime_id,
            is_alive=is_alive,
            terminate_fn=terminate_fn,
        )
        server_running = bool(stopped.running)
        if stopped.status != "ok":
            diags.extend(_as_warnings(stopped.diagnostics))

    return ctx.ok(
        attached=False,
        ping_running=False,
        running=server_running,
        diagnostics=diags,
    )

def _as_warnings(diagnostics: Sequence[Any]) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    for d in diagnostics:
        out.append(
            warning(
                str(d.get("message", "")),
                code=str(d.get("code") or CODE_DBGS_UNREACHABLE),
                source=SOURCE_DEBUG,
                suggestion=d.get("suggestion"),
            )
        )
    return out
