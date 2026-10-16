"""Debug session operations: attach / detach / targets / status / reload-metadata."""

from __future__ import annotations

import os
import time
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
from adapters.platform_1cv8 import IsRunningFn
from core.debug.common import (
    SessionFactory,
    client_debug_hint,
    fail_result,
    handle_adapter_error,
    load_project,
    make_resolver,
    ok_result,
    restore_session,
    session_url,
)
from core.debug.constants import (
    CODE_DBGS_UNREACHABLE,
    CODE_PROJECT,
    SOURCE_DEBUG,
)
from core.debug.ping import (
    soft_ensure_background_ping,
    stop_background_ping,
)
from core.debug.result import DebugResult
from core.debug.server import (
    server_status,
)
from core.debug.state import (
    alive_ping,
    alive_server,
    clear_session,
    manifest_debug_settings,
    persist_session_runtime,
    read_session,
    resolve_debugger_url,
    write_session,
)
from core.diagnostics import error


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
    root, data, target, err = load_project(
        start_path, started=started, config_id=config_id, runtime_id=runtime_id
    )
    if err is not None:
        return err
    assert target is not None
    settings = manifest_debug_settings(data)
    base = session_url(root, data, url=url)
    if not base:
        running, _pid, meta = alive_server(root)
        hint = ""
        if running and meta.get("url"):
            hint = str(meta["url"])
        return fail_result(
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
        return handle_adapter_error(exc, started=started, root=root, target=target)

    factory = session_factory or DebugSession
    types = settings["autoAttachTypes"]
    session = factory(
        client,
        alias=settings["alias"],
        resolver=make_resolver(root, target),
        auto_attach_types=types,
    )
    pwd = password if password is not None else os.environ.get("ONEC_DEBUG_PASSWORD", "")
    try:
        # CLI process exits immediately — do not start ping only to join(2s) on stop.
        attach = session.attach(password=pwd or "", start_ping=False)
    except DebugHttpError as exc:
        return handle_adapter_error(exc, started=started, root=root, target=target)

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
    client_enabled, client_url = client_debug_hint(root)
    return ok_result(
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
    root, data, target, err = load_project(
        start_path, started=started, config_id=config_id, runtime_id=runtime_id
    )
    if err is not None:
        return err
    assert target is not None
    stop_background_ping(root)
    session, base, alias, restore_err = restore_session(
        root,
        data,
        target,
        transport=transport,
        session_factory=session_factory,
    )
    if restore_err is not None and not force:
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
            return ok_result(
                started=started,
                root=root,
                config_id=target.config_id,
                runtime_id=target.runtime_id,
                attached=False,
                ping_running=False,
                diagnostics=list(exc.diagnostics),
            )
        return handle_adapter_error(exc, started=started, root=root, target=target)
    clear_session(root)
    return ok_result(
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
    root, data, target, err = load_project(
        start_path, started=started, config_id=config_id, runtime_id=runtime_id
    )
    if err is not None:
        return err
    assert target is not None
    session, base, alias, restore_err = restore_session(
        root, data, target, transport=transport, session_factory=session_factory
    )
    if restore_err is not None:
        restore_err.duration = time.perf_counter() - started
        return restore_err
    try:
        targets = session.ensure_targets_attached(force=False)
    except DebugHttpError as exc:
        return handle_adapter_error(exc, started=started, root=root, target=target)
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
    client_enabled, _ = client_debug_hint(root)
    return ok_result(
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
    root, data, target, err = load_project(
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
    client_enabled, client_url = client_debug_hint(root)
    ping_running, ping_pid, _ping_meta = alive_ping(root, is_alive=is_alive)
    return ok_result(
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


def run_reload_metadata(
    start: Path | None = None,
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
) -> DebugResult:
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    root, _data, target, err = load_project(
        start_path, started=started, config_id=config_id, runtime_id=runtime_id
    )
    if err is not None:
        return err
    assert target is not None
    roots = source_roots_from_configuration(root, target.configuration)
    if not roots:
        return fail_result(
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
    return ok_result(
        started=started,
        root=root,
        config_id=target.config_id,
        runtime_id=target.runtime_id,
        modules_count=len(index.modules),
    )
