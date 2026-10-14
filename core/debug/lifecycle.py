"""Debug lifecycle: dbgs server, attach/detach, targets, ping daemon, status."""

from __future__ import annotations

import os
import shutil
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from adapters.debug_http import (
    DebugHttpClient,
    DebugHttpError,
    DebugSession,
    TransportFn,
    reload_metadata,
    source_roots_from_configuration,
)
from adapters.platform_1cv8 import IsRunningFn, TerminateFn
from core.debug.breakpoints import parse_breakpoint_specs, run_breakpoint_set
from core.debug.common import (
    SessionFactory,
    _client_debug_hint,
    _fail,
    _handle_adapter_error,
    _load_project,
    _make_resolver,
    _ok,
    _restore_session,
    _session_url,
)
from core.debug.constants import (
    CODE_DBGS_UNREACHABLE,
    CODE_NO_SESSION,
    CODE_PROJECT,
    SOURCE_DEBUG,
)
from core.debug.ping import (
    ensure_background_ping,
    ping_status,
    soft_ensure_background_ping,
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
from core.debug.state import (
    alive_ping,
    alive_server,
    clear_session,
    eval_dir,
    manifest_debug_settings,
    persist_session_runtime,
    ping_pid_path,
    read_server_pid,
    read_session,
    reset_session_runtime,
    resolve_debugger_url,
    server_pid_path,
    session_lock_path,
    session_path,
    write_session,
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
        root, _data, target, err = _load_project(
            start_path, started=started, config_id=config_id, runtime_id=runtime_id
        )
        if err is not None:
            return err
        assert target is not None
        return _fail(
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

    root, data, target, err = _load_project(
        start_path, started=started, config_id=config_id, runtime_id=runtime_id
    )
    if err is not None:
        return err
    assert target is not None

    stored = read_session(root)
    if stored is None:
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
    else:
        # Session already on disk — validate restore path exists for BP set.
        _session, _base, _alias, restore_err = _restore_session(
            root, data, target, transport=transport, session_factory=session_factory
        )
        if restore_err is not None:
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
        else:
            soft_ensure_background_ping(root)

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
    return _ok(
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
    root, _data, target, err = _load_project(
        start_path, started=started, config_id=config_id, runtime_id=runtime_id
    )
    if err is not None:
        return err
    assert target is not None
    if read_session(root) is None:
        return _fail(
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
    return _ok(
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
    root, data, target, err = _load_project(
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
            return _fail(
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
    return _ok(
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
    root, data, target, err = _load_project(
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
        session, _base, _alias, restore_err = _restore_session(
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

    return _ok(
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
    root, data, target, err = _load_project(
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
    root, _data, target, err = _load_project(
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
    root, _data, target, err = _load_project(
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


def run_attach(
    start: Path | None = None,
    *,
    url: str | None = None,
    password: str | None = None,
    config_id: str | None = None,
    runtime_id: str | None = None,
    transport: TransportFn | None = None,
    session_factory: SessionFactory | None = None,
) -> DebugResult:
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    root, data, target, err = _load_project(
        start_path, started=started, config_id=config_id, runtime_id=runtime_id
    )
    if err is not None:
        return err
    assert target is not None
    settings = manifest_debug_settings(data)
    base = _session_url(root, data, url=url)
    if not base:
        running, _pid, meta = alive_server(root)
        hint = ""
        if running and meta.get("url"):
            hint = str(meta["url"])
        return _fail(
            started=started,
            root=root,
            config_id=target.config_id,
            runtime_id=target.runtime_id,
            diagnostics=[
                error(
                    "нет URL dbgs (server не запущен и нет debug.port)",
                    code=CODE_DBGS_UNREACHABLE,
                    source=SOURCE_DEBUG,
                    suggestion=hint
                    or "1c-dev debug server start --port … или debug.port в манифесте",
                )
            ],
        )
    client = DebugHttpClient(base, transport=transport)
    try:
        client.test()
    except DebugHttpError as exc:
        return _handle_adapter_error(exc, started=started, root=root, target=target)

    factory = session_factory or DebugSession
    types = settings["autoAttachTypes"]
    session = factory(
        client,
        alias=settings["alias"],
        resolver=_make_resolver(root, target),
        auto_attach_types=types,
    )
    pwd = password if password is not None else os.environ.get("ONEC_DEBUG_PASSWORD", "")
    try:
        # CLI process exits immediately — do not start ping only to join(2s) on stop.
        attach = session.attach(password=pwd or "", start_ping=False)
    except DebugHttpError as exc:
        return _handle_adapter_error(exc, started=started, root=root, target=target)

    write_session(
        root,
        url=base,
        alias=settings["alias"],
        session_id=attach.session_id,
    )
    # Keepalive from attach onward; wait/step poll lastStop on disk (worker writes it).
    # Do not kill the worker for in-process wait — that gap releases the stopped target.
    ping_diags = soft_ensure_background_ping(root)
    ping_running, ping_pid, _ping_meta = alive_ping(root)
    client_enabled, client_url = _client_debug_hint(root)
    return _ok(
        started=started,
        root=root,
        config_id=target.config_id,
        runtime_id=target.runtime_id,
        url=base,
        alias=settings["alias"],
        session_id=attach.session_id,
        attached=True,
        client_debug_enabled=client_enabled,
        debugger_url=client_url or base,
        ping_pid=ping_pid,
        ping_running=ping_running,
        diagnostics=ping_diags,
    )


def run_detach(
    start: Path | None = None,
    *,
    force: bool = False,
    config_id: str | None = None,
    runtime_id: str | None = None,
    transport: TransportFn | None = None,
    session_factory: SessionFactory | None = None,
) -> DebugResult:
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    root, data, target, err = _load_project(
        start_path, started=started, config_id=config_id, runtime_id=runtime_id
    )
    if err is not None:
        return err
    assert target is not None
    stop_background_ping(root)
    session, base, alias, restore_err = _restore_session(
        root,
        data,
        target,
        transport=transport,
        session_factory=session_factory,
    )
    if restore_err is not None and not force:
        # force-detach still clears local state
        if force:
            clear_session(root)
            return _ok(
                started=started,
                root=root,
                config_id=target.config_id,
                runtime_id=target.runtime_id,
                attached=False,
                ping_running=False,
            )
        restore_err.duration = time.perf_counter() - started
        return restore_err
    try:
        if force:
            session.force_detach()
        else:
            session.detach()
    except DebugHttpError as exc:
        if force:
            clear_session(root)
            return _ok(
                started=started,
                root=root,
                config_id=target.config_id,
                runtime_id=target.runtime_id,
                attached=False,
                ping_running=False,
                diagnostics=list(exc.diagnostics),
            )
        return _handle_adapter_error(exc, started=started, root=root, target=target)
    clear_session(root)
    return _ok(
        started=started,
        root=root,
        config_id=target.config_id,
        runtime_id=target.runtime_id,
        url=base or None,
        alias=alias or None,
        attached=False,
        ping_running=False,
    )


def run_force_detach(
    start: Path | None = None,
    **kwargs: Any,
) -> DebugResult:
    return run_detach(start, force=True, **kwargs)


def run_targets(
    start: Path | None = None,
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
    transport: TransportFn | None = None,
    session_factory: SessionFactory | None = None,
) -> DebugResult:
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    root, data, target, err = _load_project(
        start_path, started=started, config_id=config_id, runtime_id=runtime_id
    )
    if err is not None:
        return err
    assert target is not None
    session, base, alias, restore_err = _restore_session(
        root, data, target, transport=transport, session_factory=session_factory
    )
    if restore_err is not None:
        restore_err.duration = time.perf_counter() - started
        return restore_err
    try:
        targets = session.ensure_targets_attached(force=False)
    except DebugHttpError as exc:
        return _handle_adapter_error(exc, started=started, root=root, target=target)
    persist_session_runtime(root, session, url=base, alias=alias)
    payload = [
        {
            "targetId": t.target_id,
            "targetType": t.target_type,
            "state": t.state,
            "seanceId": t.seance_id,
            "infoBaseAlias": t.info_base_alias,
        }
        for t in targets
    ]
    client_enabled, _ = _client_debug_hint(root)
    return _ok(
        started=started,
        root=root,
        config_id=target.config_id,
        runtime_id=target.runtime_id,
        url=base,
        alias=alias,
        session_id=session.session_id,
        attached=True,
        targets=payload,
        client_debug_enabled=client_enabled,
    )


def run_status(
    start: Path | None = None,
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
    is_alive: IsRunningFn | None = None,
    transport: TransportFn | None = None,
) -> DebugResult:
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    root, data, target, err = _load_project(
        start_path, started=started, config_id=config_id, runtime_id=runtime_id
    )
    if err is not None:
        return err
    assert target is not None
    srv = server_status(
        root,
        started=started,
        config_id=target.config_id,
        runtime_id=target.runtime_id,
        is_alive=is_alive,
        transport=transport,
    )
    stored = read_session(root)
    client_enabled, client_url = _client_debug_hint(root)
    ping_running, ping_pid, _ping_meta = alive_ping(root, is_alive=is_alive)
    return _ok(
        started=started,
        root=root,
        config_id=target.config_id,
        runtime_id=target.runtime_id,
        host=srv.host,
        port=srv.port,
        url=srv.url,
        pid=srv.pid,
        running=srv.running,
        attached=stored is not None,
        session_id=str(stored["sessionId"]) if stored and stored.get("sessionId") else None,
        alias=str(stored["alias"]) if stored and stored.get("alias") else None,
        client_debug_enabled=client_enabled,
        debugger_url=client_url or resolve_debugger_url(root, data),
        ping_pid=ping_pid,
        ping_running=ping_running,
        diagnostics=list(srv.diagnostics),
    )


def run_ping_start(
    start: Path | None = None,
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
    **kwargs: Any,
) -> DebugResult:
    """Start background ``pingDebugUIParams`` keepalive (CLI between commands)."""
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    root, _data, target, err = _load_project(
        start_path, started=started, config_id=config_id, runtime_id=runtime_id
    )
    if err is not None:
        return err
    assert target is not None
    result = ensure_background_ping(root, **kwargs)
    result.duration = time.perf_counter() - started
    result.config_id = target.config_id
    result.runtime_id = target.runtime_id
    return result


def run_ping_stop(
    start: Path | None = None,
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
    **kwargs: Any,
) -> DebugResult:
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    root, _data, target, err = _load_project(
        start_path, started=started, config_id=config_id, runtime_id=runtime_id
    )
    if err is not None:
        return err
    assert target is not None
    result = stop_background_ping(root, **kwargs)
    result.duration = time.perf_counter() - started
    result.config_id = target.config_id
    result.runtime_id = target.runtime_id
    return result


def run_ping_status(
    start: Path | None = None,
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
    **kwargs: Any,
) -> DebugResult:
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    root, _data, target, err = _load_project(
        start_path, started=started, config_id=config_id, runtime_id=runtime_id
    )
    if err is not None:
        return err
    assert target is not None
    result = ping_status(root, **kwargs)
    result.duration = time.perf_counter() - started
    result.config_id = target.config_id
    result.runtime_id = target.runtime_id
    return result


def run_reload_metadata(
    start: Path | None = None,
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
) -> DebugResult:
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    root, _data, target, err = _load_project(
        start_path, started=started, config_id=config_id, runtime_id=runtime_id
    )
    if err is not None:
        return err
    assert target is not None
    roots = source_roots_from_configuration(root, target.configuration)
    if not roots:
        return _fail(
            started=started,
            root=root,
            config_id=target.config_id,
            runtime_id=target.runtime_id,
            diagnostics=[
                error(
                    "нет source.path у configuration / extensions",
                    code=CODE_PROJECT,
                    source=SOURCE_DEBUG,
                )
            ],
        )
    index = reload_metadata(root, roots)
    return _ok(
        started=started,
        root=root,
        config_id=target.config_id,
        runtime_id=target.runtime_id,
        modules_count=len(index.modules),
    )
