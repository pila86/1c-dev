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
    fail_result,
    load_project,
    ok_result,
    restore_session,
)
from core.debug.constants import (
    CODE_DBGS_UNREACHABLE,
    CODE_NO_SESSION,
    SOURCE_DEBUG,
)
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
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    raw_bps = list(breakpoints or [])
    specs, parse_diags = parse_breakpoint_specs(raw_bps)
    if parse_diags:
        root, _data, target, err = load_project(
            start_path, started=started, config_id=config_id, runtime_id=runtime_id
        )
        if err is not None:
            return err
        assert target is not None
        return fail_result(
            started=started,
            root=root,
            config_id=target.config_id,
            runtime_id=target.runtime_id,
            diagnostics=parse_diags,
        )

    server = run_server_start(
        start_path,
        config_id=config_id,
        runtime_id=runtime_id,
        discover=discover,
        spawn=spawn,
        is_alive=is_alive,
        transport=transport,
    )
    if server.status != "ok":
        server.duration = time.perf_counter() - started
        return server

    root, data, target, err = load_project(
        start_path, started=started, config_id=config_id, runtime_id=runtime_id
    )
    if err is not None:
        return err
    assert target is not None

    need_attach = read_session(root) is None
    if not need_attach:
        # Session already on disk — validate that it can be restored for BP set.
        _session, _base, _alias, restore_err = restore_session(
            root, data, target, transport=transport, session_factory=session_factory
        )
        if restore_err is None:
            soft_ensure_background_ping(root)
        else:
            need_attach = True
    if need_attach:
        attached = run_attach(
            start_path,
            url=debugger_url or server.url,
            config_id=config_id,
            runtime_id=runtime_id,
            transport=transport,
            session_factory=session_factory,
        )
        if attached.status != "ok":
            attached.duration = time.perf_counter() - started
            return attached

    bp_out: list[dict[str, Any]] = []
    for spec in specs:
        set_result = run_breakpoint_set(
            start_path,
            file=spec.file,
            lines=spec.lines,
            config_id=config_id,
            runtime_id=runtime_id,
            transport=transport,
            session_factory=session_factory,
        )
        if set_result.status != "ok":
            set_result.duration = time.perf_counter() - started
            return set_result
        bp_out.extend(set_result.breakpoints)

    base = (
        debugger_url
        or server.url
        or resolve_debugger_url(root, data, explicit=debugger_url)
    )
    session_meta = read_session(root) or {}
    return ok_result(
        started=started,
        root=root,
        config_id=target.config_id,
        runtime_id=target.runtime_id,
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
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    root, _data, target, err = load_project(
        start_path, started=started, config_id=config_id, runtime_id=runtime_id
    )
    if err is not None:
        return err
    assert target is not None
    if read_session(root) is None:
        return fail_result(
            started=started,
            root=root,
            config_id=target.config_id,
            runtime_id=target.runtime_id,
            diagnostics=[
                error(
                    "нет активной debug-сессии",
                    code=CODE_NO_SESSION,
                    source=SOURCE_DEBUG,
                    suggestion="выполните 1c-dev debug attach",
                )
            ],
        )
    reset_session_runtime(root)
    diags = soft_ensure_background_ping(root, **ping_kwargs)
    return ok_result(
        started=started,
        root=root,
        config_id=target.config_id,
        runtime_id=target.runtime_id,
        attached=True,
        diagnostics=diags,
    )


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
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    root, data, target, err = load_project(
        start_path, started=started, config_id=config_id, runtime_id=runtime_id
    )
    if err is not None:
        return err
    assert target is not None
    ping_diags = soft_ensure_background_ping(root)
    deadline = started + max(0.0, timeout)
    targets: list[str] = []
    while True:
        stored = read_session(root)
        if stored is None:
            return fail_result(
                started=started,
                root=root,
                config_id=target.config_id,
                runtime_id=target.runtime_id,
                diagnostics=[
                    error(
                        "нет активной debug-сессии",
                        code=CODE_NO_SESSION,
                        source=SOURCE_DEBUG,
                        suggestion="выполните 1c-dev debug attach",
                    )
                ],
            )
        raw = stored.get("attachedTargets")
        targets = [str(t) for t in raw if isinstance(t, str) and t] if isinstance(raw, list) else []
        if targets or time.perf_counter() >= deadline:
            break
        time.sleep(max(0.02, poll_interval))
    base = str(stored.get("url") or "") or resolve_debugger_url(root, data)
    return ok_result(
        started=started,
        root=root,
        config_id=target.config_id,
        runtime_id=target.runtime_id,
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
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    root, data, target, err = load_project(
        start_path, started=started, config_id=config_id, runtime_id=runtime_id
    )
    if err is not None:
        return err
    assert target is not None
    diags: list[Diagnostic] = []

    ping = stop_background_ping(
        root, is_alive=is_alive, terminate_fn=terminate_fn
    )
    if ping.status != "ok":
        diags.extend(_as_warnings(ping.diagnostics))

    if read_session(root) is not None:
        session, _base, _alias, restore_err = restore_session(
            root,
            data,
            target,
            transport=transport,
            session_factory=session_factory,
        )
        if restore_err is None:
            try:
                session.force_detach()
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
            started=started,
            config_id=target.config_id,
            runtime_id=target.runtime_id,
            is_alive=is_alive,
            terminate_fn=terminate_fn,
        )
        server_running = bool(stopped.running)
        if stopped.status != "ok":
            diags.extend(_as_warnings(stopped.diagnostics))

    return ok_result(
        started=started,
        root=root,
        config_id=target.config_id,
        runtime_id=target.runtime_id,
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
