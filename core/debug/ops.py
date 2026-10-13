"""Debug API orchestration over ``adapters.debug_http`` (ADR-031 / #140)."""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from adapters.debug_http import (
    DEFAULT_WAIT_TIMEOUT_SEC,
    BreakpointSpec,
    DebugHttpClient,
    DebugHttpError,
    DebugSession,
    StackFrame,
    StopEvent,
    TransportFn,
    XmlObjectIdResolver,
    reload_metadata,
    source_roots_from_configuration,
)
from adapters.debug_http.constants import CODE_MODULE_UNRESOLVED
from adapters.platform_1cv8 import IsRunningFn, TerminateFn
from core.debug.constants import (
    CODE_DBGS_UNREACHABLE,
    CODE_NO_SESSION,
    CODE_PROJECT,
    DEFAULT_ALIAS,
    SOURCE_DEBUG,
)
from core.debug.result import DebugResult, exit_code_for_result
from core.debug.server import (
    DiscoverFn,
    SpawnDbgsFn,
    server_start,
    server_status,
    server_stop,
)
from core.debug.state import (
    alive_server,
    clear_session,
    manifest_debug_settings,
    persist_session_runtime,
    read_session,
    resolve_debugger_url,
    write_session,
)
from core.diagnostics import Diagnostic, error
from core.exit_codes import SUCCESS
from core.project.constants import HOME_MANIFEST_REL
from core.project.detect import detect_manifest
from core.project.load import load_manifest
from core.project.paths import scope_root_from_manifest
from core.project.resolve import ResolvedTarget, resolve_config_runtime
from core.runtime.state import read_meta

SessionFactory = Callable[..., DebugSession]


def _fail(
    *,
    started: float,
    diagnostics: list[Diagnostic],
    root: Path | None = None,
    config_id: str | None = None,
    runtime_id: str | None = None,
    **kwargs: Any,
) -> DebugResult:
    return DebugResult(
        status="failed",
        duration=time.perf_counter() - started,
        root=root,
        config_id=config_id,
        runtime_id=runtime_id,
        diagnostics=list(diagnostics),
        exit_code=exit_code_for_result("failed", diagnostics),
        **kwargs,
    )


def _ok(
    *,
    started: float,
    root: Path | None = None,
    config_id: str | None = None,
    runtime_id: str | None = None,
    diagnostics: list[Diagnostic] | None = None,
    **kwargs: Any,
) -> DebugResult:
    diags = list(diagnostics or [])
    return DebugResult(
        status="ok",
        duration=time.perf_counter() - started,
        root=root,
        config_id=config_id,
        runtime_id=runtime_id,
        diagnostics=diags,
        exit_code=SUCCESS,
        **kwargs,
    )


def _load_project(
    start: Path,
    *,
    started: float,
    config_id: str | None,
    runtime_id: str | None,
    require_runtime: bool = False,
) -> tuple[Path, dict[str, Any], ResolvedTarget | None, DebugResult | None]:
    manifest_path = detect_manifest(start)
    if manifest_path is None:
        return (
            start,
            {},
            None,
            _fail(
                started=started,
                diagnostics=[
                    error(
                        f"Файл {HOME_MANIFEST_REL} не найден",
                        code=CODE_PROJECT,
                        source=SOURCE_DEBUG,
                        suggestion="Выполните 1c-dev init --type configuration",
                    )
                ],
            ),
        )
    data, load_diags = load_manifest(manifest_path)
    root = scope_root_from_manifest(manifest_path)
    if data is None:
        return (
            root,
            {},
            None,
            _fail(
                started=started,
                root=root,
                diagnostics=list(load_diags)
                or [
                    error(
                        "Не удалось прочитать манифест",
                        code=CODE_PROJECT,
                        source=SOURCE_DEBUG,
                    )
                ],
            ),
        )
    target, resolve_diags = resolve_config_runtime(
        data,
        config_id=config_id,
        runtime_id=runtime_id,
        require_runtime=require_runtime,
    )
    if target is None:
        return (
            root,
            data,
            None,
            _fail(
                started=started,
                root=root,
                diagnostics=list(resolve_diags)
                or [
                    error(
                        "Не удалось разрешить --config/--runtime",
                        code=CODE_PROJECT,
                        source=SOURCE_DEBUG,
                    )
                ],
            ),
        )
    return root, data, target, None


def _client_debug_hint(root: Path) -> tuple[bool | None, str | None]:
    meta = read_meta(root)
    debug = meta.get("debug")
    if not isinstance(debug, dict):
        return None, None
    enabled = bool(debug.get("enabled", False))
    url = debug.get("debuggerUrl")
    url_s = url.strip() if isinstance(url, str) and url.strip() else None
    return enabled, url_s


def _session_url(
    root: Path,
    data: dict[str, Any],
    *,
    url: str | None = None,
) -> str | None:
    if url and url.strip():
        return url.strip().rstrip("/")
    stored = read_session(root)
    if stored and isinstance(stored.get("url"), str) and stored["url"].strip():
        return str(stored["url"]).rstrip("/")
    return resolve_debugger_url(root, data)


def _make_resolver(
    root: Path,
    target: ResolvedTarget,
) -> XmlObjectIdResolver:
    return XmlObjectIdResolver.from_configuration(root, target.configuration)


def _restore_session(
    root: Path,
    data: dict[str, Any],
    target: ResolvedTarget,
    *,
    transport: TransportFn | None = None,
    session_factory: SessionFactory | None = None,
    url: str | None = None,
    start_ping: bool = False,
) -> tuple[DebugSession, str, str, DebugResult | None]:
    """Rebuild ``DebugSession`` from disk state (CLI is short-lived)."""
    stored = read_session(root)
    if stored is None:
        return (
            DebugSession(DebugHttpClient("http://localhost:0", transport=transport)),
            "",
            "",
            _fail(
                started=time.perf_counter(),
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
            ),
        )
    settings = manifest_debug_settings(data)
    base = url or stored.get("url")
    if not isinstance(base, str) or not base.strip():
        base = resolve_debugger_url(root, data)
    if not base:
        return (
            DebugSession(DebugHttpClient("http://localhost:0", transport=transport)),
            "",
            "",
            _fail(
                started=time.perf_counter(),
                root=root,
                diagnostics=[
                    error(
                        "нет URL dbgs для сессии",
                        code=CODE_DBGS_UNREACHABLE,
                        source=SOURCE_DEBUG,
                        suggestion="debug server start или debug.host/port в манифесте",
                    )
                ],
            ),
        )
    alias = str(stored.get("alias") or settings["alias"] or DEFAULT_ALIAS)
    session_id = str(stored.get("sessionId") or "")
    if not session_id:
        return (
            DebugSession(DebugHttpClient(base, transport=transport)),
            base,
            alias,
            _fail(
                started=time.perf_counter(),
                root=root,
                diagnostics=[
                    error(
                        "session.json без sessionId",
                        code=CODE_NO_SESSION,
                        source=SOURCE_DEBUG,
                    )
                ],
            ),
        )
    client = DebugHttpClient(base.rstrip("/"), transport=transport)
    factory = session_factory or DebugSession
    types = settings["autoAttachTypes"]
    session = factory(
        client,
        alias=alias,
        session_id=session_id,
        resolver=_make_resolver(root, target),
        auto_attach_types=types,
    )
    session._attached = True  # noqa: SLF001 — restore across CLI processes
    _apply_stored_runtime(session, stored)
    if start_ping:
        session.start_ping()
    return session, base.rstrip("/"), alias, None


def _apply_stored_runtime(session: DebugSession, stored: dict[str, Any]) -> None:
    """Hydrate stop/targets/BP from ``session.json`` (short-lived CLI)."""
    raw_targets = stored.get("attachedTargets")
    if isinstance(raw_targets, list):
        session._attached_targets = {  # noqa: SLF001
            str(t) for t in raw_targets if isinstance(t, str) and t
        }
    last_tid = stored.get("lastTargetId")
    if isinstance(last_tid, str) and last_tid.strip():
        session._last_target_id = last_tid.strip()  # noqa: SLF001

    raw_bps = stored.get("breakpoints")
    if isinstance(raw_bps, list):
        restored: list[BreakpointSpec] = []
        for item in raw_bps:
            if not isinstance(item, dict):
                continue
            oid = str(item.get("objectId") or "")
            pid = str(item.get("propertyId") or "")
            lines_raw = item.get("lines") or []
            if not oid or not pid or not isinstance(lines_raw, list):
                continue
            lines = tuple(int(x) for x in lines_raw if isinstance(x, int) or str(x).isdigit())
            if not lines:
                continue
            restored.append(
                BreakpointSpec(
                    object_id=oid,
                    property_id=pid,
                    lines=lines,
                    extension_name=str(item.get("extensionName") or ""),
                )
            )
        session._breakpoints = restored  # noqa: SLF001

    raw_stop = stored.get("lastStop")
    if not isinstance(raw_stop, dict):
        return
    frames_raw = raw_stop.get("frames") or []
    frames: list[StackFrame] = []
    if isinstance(frames_raw, list):
        for fr in frames_raw:
            if not isinstance(fr, dict):
                continue
            frames.append(
                StackFrame(
                    object_id=str(fr.get("objectId") or ""),
                    property_id=str(fr.get("propertyId") or ""),
                    line_no=int(fr.get("lineNo") or 0),
                    module_name=str(fr.get("moduleName") or ""),
                )
            )
    target_id = str(raw_stop.get("targetId") or "")
    if not frames and not target_id:
        return
    session._last_stop = StopEvent(  # noqa: SLF001
        target_id=target_id,
        frames=tuple(frames),
    )
    session._stop_event.set()  # noqa: SLF001
    if target_id:
        session._attached_targets.add(target_id)  # noqa: SLF001
        if not session._last_target_id:  # noqa: SLF001
            session._last_target_id = target_id  # noqa: SLF001


def _frames_payload(frames: Sequence[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for frame in frames:
        out.append(
            {
                "objectId": frame.object_id,
                "propertyId": frame.property_id,
                "lineNo": frame.line_no,
                "moduleName": frame.module_name,
            }
        )
    return out


def _vars_payload(eval_result: Any) -> list[dict[str, Any]]:
    return [
        {
            "name": v.name,
            "type": v.type_name,
            "presentation": v.presentation,
            "value": v.value_raw,
        }
        for v in eval_result.variables
    ]


def _handle_adapter_error(
    exc: DebugHttpError,
    *,
    started: float,
    root: Path,
    target: ResolvedTarget | None,
) -> DebugResult:
    return _fail(
        started=started,
        root=root,
        config_id=target.config_id if target else None,
        runtime_id=target.runtime_id if target else None,
        diagnostics=list(exc.diagnostics),
    )


# --- public API ------------------------------------------------------------


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
        attach = session.attach(password=pwd or "", start_ping=True)
    except DebugHttpError as exc:
        session.stop_ping()
        return _handle_adapter_error(exc, started=started, root=root, target=target)

    write_session(
        root,
        url=base,
        alias=settings["alias"],
        session_id=attach.session_id,
    )
    # Ping stays for this process only; CLI exits → loop stops (session remains on dbgs).
    session.stop_ping()
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
        targets = session.ensure_targets_attached(force=True)
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


def run_breakpoint_set(
    start: Path | None = None,
    *,
    module: str | None = None,
    module_type: str = "CommonModule",
    lines: Sequence[int],
    extension: str | None = None,
    file: str | Path | None = None,
    object_id: str | None = None,
    property_id: str | None = None,
    config_id: str | None = None,
    runtime_id: str | None = None,
    transport: TransportFn | None = None,
    session_factory: SessionFactory | None = None,
) -> DebugResult:
    """Set breakpoints by ``--module``, ``--file``, or explicit object/property ids (#145)."""
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    root, data, target, err = _load_project(
        start_path, started=started, config_id=config_id, runtime_id=runtime_id
    )
    if err is not None:
        return err
    assert target is not None
    if not lines:
        return _fail(
            started=started,
            root=root,
            config_id=target.config_id,
            runtime_id=target.runtime_id,
            diagnostics=[
                error(
                    "нужна хотя бы одна строка breakpoint",
                    code=CODE_PROJECT,
                    source=SOURCE_DEBUG,
                )
            ],
        )

    has_module = bool(module and str(module).strip())
    has_file = file is not None and str(file).strip() != ""
    has_ids = bool(
        object_id and str(object_id).strip() and property_id and str(property_id).strip()
    )
    modes = sum(1 for flag in (has_module, has_file, has_ids) if flag)
    if modes != 1:
        return _fail(
            started=started,
            root=root,
            config_id=target.config_id,
            runtime_id=target.runtime_id,
            diagnostics=[
                error(
                    "укажите ровно один способ: --module, --file "
                    "или пару --object-id/--property-id",
                    code=CODE_PROJECT,
                    source=SOURCE_DEBUG,
                    suggestion=(
                        "1c-dev debug breakpoint set --file Catalogs/X/Ext/ObjectModule.bsl "
                        "--lines 5"
                    ),
                )
            ],
        )

    session, base, alias, restore_err = _restore_session(
        root, data, target, transport=transport, session_factory=session_factory
    )
    if restore_err is not None:
        restore_err.duration = time.perf_counter() - started
        return restore_err
    try:
        if has_file:
            assert file is not None
            resolve_file = getattr(session.resolver, "resolve_from_file", None)
            if resolve_file is None:
                raise DebugHttpError(
                    "resolver не поддерживает resolve_from_file",
                    code=CODE_MODULE_UNRESOLVED,
                )
            ref = resolve_file(file, extension_name=extension)
            spec = session.set_breakpoints_by_ids(
                ref.object_id,
                ref.property_id,
                lines,
                extension_name=ref.extension_name or extension,
            )
            module_name_out = ref.module_name or str(file)
            module_type_out = ref.module_type or ""
        elif has_ids:
            assert object_id is not None and property_id is not None
            spec = session.set_breakpoints_by_ids(
                object_id, property_id, lines, extension_name=extension
            )
            module_name_out = ""
            module_type_out = ""
        else:
            assert module is not None
            spec = session.set_breakpoints_by_module(
                module,
                module_type,
                lines,
                extension_name=extension,
            )
            module_name_out = module
            module_type_out = module_type
        # Arm BP on already-running targets (CLI may have missed targetStarted)
        session.ensure_targets_attached(force=True)
    except DebugHttpError as exc:
        # 1CD004 from missing source → project (2); otherwise runtime
        result = _handle_adapter_error(exc, started=started, root=root, target=target)
        if any(d.get("code") == CODE_MODULE_UNRESOLVED for d in result.diagnostics):
            result.exit_code = exit_code_for_result("failed", result.diagnostics)
        return result
    persist_session_runtime(root, session, url=base, alias=alias)
    return _ok(
        started=started,
        root=root,
        config_id=target.config_id,
        runtime_id=target.runtime_id,
        url=base,
        alias=alias,
        session_id=session.session_id,
        attached=True,
        module_name=module_name_out or None,
        breakpoints=[
            {
                "objectId": spec.object_id,
                "propertyId": spec.property_id,
                "lines": list(spec.lines),
                "extensionName": spec.extension_name,
                "moduleName": module_name_out,
                "moduleType": module_type_out,
                "file": str(file) if has_file else None,
            }
        ],
    )


def run_breakpoint_clear(
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
        session.clear_breakpoints()
    except DebugHttpError as exc:
        return _handle_adapter_error(exc, started=started, root=root, target=target)
    persist_session_runtime(root, session, url=base, alias=alias)
    return _ok(
        started=started,
        root=root,
        config_id=target.config_id,
        runtime_id=target.runtime_id,
        url=base,
        alias=alias,
        session_id=session.session_id,
        attached=True,
        breakpoints=[],
    )


def run_wait(
    start: Path | None = None,
    *,
    timeout: float = DEFAULT_WAIT_TIMEOUT_SEC,
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
        root,
        data,
        target,
        transport=transport,
        session_factory=session_factory,
        start_ping=True,
    )
    if restore_err is not None:
        restore_err.duration = time.perf_counter() - started
        return restore_err
    try:
        stop = session.wait_for_stop(timeout=timeout)
    except DebugHttpError as exc:
        session.stop_ping()
        return _handle_adapter_error(exc, started=started, root=root, target=target)
    finally:
        session.stop_ping()
    frames = _frames_payload(stop.frames)
    leaf = stop.current_frame
    persist_session_runtime(root, session, url=base, alias=alias)
    return _ok(
        started=started,
        root=root,
        config_id=target.config_id,
        runtime_id=target.runtime_id,
        url=base,
        alias=alias,
        session_id=session.session_id,
        attached=True,
        target_id=stop.target_id,
        module_name=leaf.module_name if leaf else None,
        line_no=leaf.line_no if leaf else None,
        call_stack=frames,
    )


def _run_step(
    action: str,
    start: Path | None = None,
    *,
    target_id: str | None = None,
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
        if action == "Continue":
            session.continue_(target_id)
        elif action == "StepIn":
            session.step_in(target_id)
        elif action == "StepOut":
            session.step_out(target_id)
        elif action == "Pause":
            session.pause()
        else:
            return _fail(
                started=started,
                root=root,
                diagnostics=[
                    error(f"неизвестное действие {action}", code=CODE_PROJECT, source=SOURCE_DEBUG)
                ],
            )
    except DebugHttpError as exc:
        return _handle_adapter_error(exc, started=started, root=root, target=target)
    # Continue/step leave stopped state; persist cleared stop for next CLI process.
    clear_stop = action in ("Continue", "StepIn", "StepOut")
    if clear_stop:
        session._last_stop = None  # noqa: SLF001
        session._stop_event.clear()  # noqa: SLF001
    persist_session_runtime(
        root, session, url=base, alias=alias, clear_last_stop=clear_stop
    )
    return _ok(
        started=started,
        root=root,
        config_id=target.config_id,
        runtime_id=target.runtime_id,
        url=base,
        alias=alias,
        session_id=session.session_id,
        attached=True,
        target_id=target_id,
    )


def run_continue(start: Path | None = None, **kwargs: Any) -> DebugResult:
    return _run_step("Continue", start, **kwargs)


def run_step_in(start: Path | None = None, **kwargs: Any) -> DebugResult:
    return _run_step("StepIn", start, **kwargs)


def run_step_out(start: Path | None = None, **kwargs: Any) -> DebugResult:
    return _run_step("StepOut", start, **kwargs)


def run_pause(start: Path | None = None, **kwargs: Any) -> DebugResult:
    return _run_step("Pause", start, **kwargs)


def run_stack(
    start: Path | None = None,
    *,
    target_id: str | None = None,
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
        frames = session.stack(target_id)
    except DebugHttpError as exc:
        return _handle_adapter_error(exc, started=started, root=root, target=target)
    payload = _frames_payload(frames)
    leaf = frames[-1] if frames else None
    return _ok(
        started=started,
        root=root,
        config_id=target.config_id,
        runtime_id=target.runtime_id,
        url=base,
        alias=alias,
        session_id=session.session_id,
        attached=True,
        target_id=target_id or (session.last_stop.target_id if session.last_stop else None),
        module_name=leaf.module_name if leaf else None,
        line_no=leaf.line_no if leaf else None,
        call_stack=payload,
    )


def run_variables(
    start: Path | None = None,
    *,
    target_id: str | None = None,
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
        result = session.variables(target_id)
    except DebugHttpError as exc:
        return _handle_adapter_error(exc, started=started, root=root, target=target)
    return _ok(
        started=started,
        root=root,
        config_id=target.config_id,
        runtime_id=target.runtime_id,
        url=base,
        alias=alias,
        session_id=session.session_id,
        attached=True,
        target_id=target_id or (session.last_stop.target_id if session.last_stop else None),
        eval_state=result.state,
        variables=_vars_payload(result),
    )


def run_evaluate(
    start: Path | None = None,
    *,
    expression: str,
    target_id: str | None = None,
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
        result = session.evaluate(expression, target_id)
    except DebugHttpError as exc:
        return _handle_adapter_error(exc, started=started, root=root, target=target)
    return _ok(
        started=started,
        root=root,
        config_id=target.config_id,
        runtime_id=target.runtime_id,
        url=base,
        alias=alias,
        session_id=session.session_id,
        attached=True,
        target_id=target_id or (session.last_stop.target_id if session.last_stop else None),
        expression=expression,
        eval_state=result.state,
        variables=_vars_payload(result),
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
