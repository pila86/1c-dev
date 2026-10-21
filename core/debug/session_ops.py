"""Debug session operations: attach / detach / targets / status / reload-metadata."""

from __future__ import annotations

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
    make_resolver,
    resolve_debug_password,
    restore_session,
    session_url,
)
from core.debug.constants import (
    CODE_DBGS_UNREACHABLE,
    CODE_PROJECT,
    SOURCE_DEBUG,
)
from core.debug.context import DebugContext
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
    settings = manifest_debug_settings(ctx.data)
    base = session_url(root, ctx.data, url=url)
    if not base:
        running, _pid, meta = alive_server(root)
        hint = ""
        if running and meta.get("url"):
            hint = str(meta["url"])
        return ctx.fail(
            [
                error(
                    "нет URL dbgs (server не запущен и нет debug.port)",
                    code=CODE_DBGS_UNREACHABLE,
                    source=SOURCE_DEBUG,
                    suggestion=hint
                    or "1c-dev debug server start --port … или debug.port в манифесте",
                )
            ]
        )
    client = DebugHttpClient(base, transport=transport)
    try:
        client.test()
    except DebugHttpError as exc:
        return ctx.adapter_error(exc)

    factory = session_factory or DebugSession
    types = settings["autoAttachTypes"]
    session = factory(
        client,
        alias=settings["alias"],
        resolver=make_resolver(root, ctx.target),
        auto_attach_types=types,
    )
    pwd = resolve_debug_password(password)
    try:
        # CLI process exits immediately — do not start ping only to join(2s) on stop.
        attach = session.attach(password=pwd, start_ping=False)
    except DebugHttpError as exc:
        return ctx.adapter_error(exc)

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
    return ctx.ok(
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
    stop_background_ping(root)
    session, base, alias, restore_err = restore_session(
        root,
        ctx.data,
        ctx.target,
        transport=transport,
        session_factory=session_factory,
    )
    if restore_err is not None and not force:
        restore_err.duration = time.perf_counter() - ctx.started
        return restore_err
    try:
        if force:
            session.force_detach()
        else:
            session.detach()
    except DebugHttpError as exc:
        if force:
            clear_session(root)
            return ctx.ok(attached=False, ping_running=False, diagnostics=list(exc.diagnostics))
        return ctx.adapter_error(exc)
    clear_session(root)
    return ctx.ok(url=base or None, alias=alias or None, attached=False, ping_running=False)


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
    ctx = DebugContext.open(
        start,
        config_id=config_id,
        runtime_id=runtime_id,
        transport=transport,
        session_factory=session_factory,
    )
    if isinstance(ctx, DebugResult):
        return ctx
    restored = ctx.restore()
    if isinstance(restored, DebugResult):
        return restored
    session = restored.session
    try:
        targets = session.ensure_targets_attached(force=False)
    except DebugHttpError as exc:
        return ctx.adapter_error(exc)
    ctx.persist(restored)
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
    client_enabled, _ = client_debug_hint(ctx.root)
    return ctx.ok_attached(restored, targets=payload, client_debug_enabled=client_enabled)


def run_status(
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
    root = ctx.root
    srv = server_status(
        root,
        started=ctx.started,
        config_id=ctx.config_id,
        runtime_id=ctx.runtime_id,
        is_alive=is_alive,
        transport=transport,
    )
    stored = read_session(root)
    client_enabled, client_url = client_debug_hint(root)
    ping_running, ping_pid, _ping_meta = alive_ping(root, is_alive=is_alive)
    return ctx.ok(
        host=srv.host,
        port=srv.port,
        url=srv.url,
        pid=srv.pid,
        running=srv.running,
        attached=stored is not None,
        session_id=str(stored["sessionId"]) if stored and stored.get("sessionId") else None,
        alias=str(stored["alias"]) if stored and stored.get("alias") else None,
        client_debug_enabled=client_enabled,
        debugger_url=client_url or resolve_debugger_url(root, ctx.data),
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
    ctx = DebugContext.open(start, config_id=config_id, runtime_id=runtime_id)
    if isinstance(ctx, DebugResult):
        return ctx
    roots = source_roots_from_configuration(ctx.root, ctx.target.configuration)
    if not roots:
        return ctx.fail(
            [
                error(
                    "нет source.path у configuration / extensions",
                    code=CODE_PROJECT,
                    source=SOURCE_DEBUG,
                )
            ]
        )
    index = reload_metadata(ctx.root, roots)
    return ctx.ok(modules_count=len(index.modules))
