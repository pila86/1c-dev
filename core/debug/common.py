"""Shared helpers for debug orchestration (project load, session restore, results)."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from adapters.debug_http import (
    BreakpointSpec,
    DebugHttpClient,
    DebugHttpError,
    DebugSession,
    StackFrame,
    StopEvent,
    TransportFn,
    XmlObjectIdResolver,
)
from core.debug.constants import (
    CODE_DBGS_UNREACHABLE,
    CODE_NO_SESSION,
    CODE_PROJECT,
    DEFAULT_ALIAS,
    SOURCE_DEBUG,
)
from core.debug.result import DebugResult, exit_code_for_result
from core.debug.state import (
    manifest_debug_settings,
    read_session,
    resolve_debugger_url,
    wait_eval_result,
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


def fail_result(
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


def ok_result(
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


def load_project(
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
            fail_result(
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
            fail_result(
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
            fail_result(
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


def client_debug_hint(root: Path) -> tuple[bool | None, str | None]:
    meta = read_meta(root)
    debug = meta.get("debug")
    if not isinstance(debug, dict):
        return None, None
    enabled = bool(debug.get("enabled", False))
    url = debug.get("debuggerUrl")
    url_s = url.strip() if isinstance(url, str) and url.strip() else None
    return enabled, url_s


def session_url(
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


def make_resolver(
    root: Path,
    target: ResolvedTarget,
) -> XmlObjectIdResolver:
    return XmlObjectIdResolver.from_configuration(root, target.configuration)


def restore_session(
    root: Path,
    data: dict[str, Any],
    target: ResolvedTarget,
    *,
    transport: TransportFn | None = None,
    session_factory: SessionFactory | None = None,
    url: str | None = None,
    start_ping: bool = False,
    ping_interval: float | None = None,
) -> tuple[DebugSession, str, str, DebugResult | None]:
    """Rebuild ``DebugSession`` from disk state (CLI is short-lived)."""
    stored = read_session(root)
    if stored is None:
        return (
            DebugSession(DebugHttpClient("http://localhost:0", transport=transport)),
            "",
            "",
            fail_result(
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
            fail_result(
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
            fail_result(
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
    session_kwargs: dict[str, Any] = {
        "alias": alias,
        "session_id": session_id,
        "resolver": make_resolver(root, target),
        "auto_attach_types": types,
    }
    if ping_interval is not None:
        session_kwargs["ping_interval"] = ping_interval
    session = factory(client, **session_kwargs)
    session.eval_result_reader = lambda rid, timeout: wait_eval_result(root, rid, timeout)
    session._attached = True  # noqa: SLF001 — restore across CLI processes
    if ping_interval is not None:
        session.ping_interval = ping_interval
    apply_stored_runtime(session, stored)
    if start_ping:
        session.start_ping()
    return session, base.rstrip("/"), alias, None


def apply_stored_runtime(session: DebugSession, stored: dict[str, Any]) -> None:
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
                    module_type=str(fr.get("moduleType") or ""),
                    extension_name=str(fr.get("extensionName") or ""),
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
        # Prefer stopped target over a stale lastTargetId (auto-arm used to
        # overwrite it with another target from getDbgAllTargetStates).
        session._last_target_id = target_id  # noqa: SLF001


def frames_payload(frames: Sequence[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for frame in frames:
        item: dict[str, Any] = {
            "objectId": frame.object_id,
            "propertyId": frame.property_id,
            "lineNo": frame.line_no,
            "moduleName": frame.module_name,
        }
        module_type = getattr(frame, "module_type", "") or ""
        if module_type:
            item["moduleType"] = module_type
        extension_name = getattr(frame, "extension_name", "") or ""
        if extension_name:
            item["extensionName"] = extension_name
        out.append(item)
    return out


def vars_payload(eval_result: Any) -> list[dict[str, Any]]:
    return [
        {
            "name": v.name,
            "type": v.type_name,
            "presentation": v.presentation,
            "value": v.value_raw or v.presentation,
        }
        for v in eval_result.variables
    ]


def eval_result_text(eval_result: Any) -> str | None:
    """Single presentation for evalExpr (first unnamed or first variable)."""
    vars_ = list(getattr(eval_result, "variables", ()) or ())
    if not vars_:
        return None
    for var in vars_:
        if not (var.name or "").strip():
            return var.presentation or var.value_raw or None
    return vars_[0].presentation or vars_[0].value_raw or None


def handle_adapter_error(
    exc: DebugHttpError,
    *,
    started: float,
    root: Path,
    target: ResolvedTarget | None,
) -> DebugResult:
    return fail_result(
        started=started,
        root=root,
        config_id=target.config_id if target else None,
        runtime_id=target.runtime_id if target else None,
        diagnostics=list(exc.diagnostics),
    )
