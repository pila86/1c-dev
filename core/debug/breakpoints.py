"""Breakpoint parsing and CLI/MCP operations."""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from adapters.debug_http import (
    DebugHttpError,
    TransportFn,
)
from adapters.debug_http.constants import CODE_MODULE_UNRESOLVED
from core.debug.common import (
    SessionFactory,
    _fail,
    _handle_adapter_error,
    _load_project,
    _ok,
    _restore_session,
)
from core.debug.constants import (
    CODE_PROJECT,
    SOURCE_DEBUG,
)
from core.debug.result import DebugResult, exit_code_for_result
from core.debug.state import (
    persist_session_runtime,
)
from core.diagnostics import Diagnostic, error


@dataclass(frozen=True)
class BreakpointCliSpec:
    """Parsed ``--bp path/to.bsl:line[,line…]`` for ``runtime start --debug``."""

    file: str
    lines: tuple[int, ...]


def parse_breakpoint_specs(
    raw: Sequence[str],
) -> tuple[list[BreakpointCliSpec], list[Diagnostic]]:
    """Parse repeatable ``--bp file:line[,line…]``; merge lines for the same file."""
    merged: dict[str, list[int]] = {}
    diagnostics: list[Diagnostic] = []
    for item in raw:
        text = str(item).strip()
        if not text:
            continue
        if ":" not in text:
            diagnostics.append(
                error(
                    f"неверный --bp '{text}': нужен формат path/to.bsl:line",
                    code=CODE_PROJECT,
                    source=SOURCE_DEBUG,
                    suggestion='например --bp src/main/Ext/ManagedApplicationModule.bsl:4',
                )
            )
            continue
        path_part, lines_part = text.rsplit(":", 1)
        path_part = path_part.strip()
        lines_part = lines_part.strip()
        if not path_part or not lines_part:
            diagnostics.append(
                error(
                    f"неверный --bp '{text}': пустой путь или номер строки",
                    code=CODE_PROJECT,
                    source=SOURCE_DEBUG,
                    suggestion='например --bp Catalogs/X/Ext/ObjectModule.bsl:5',
                )
            )
            continue
        lines: list[int] = []
        bad = False
        for part in lines_part.split(","):
            part = part.strip()
            if not part.isdigit():
                diagnostics.append(
                    error(
                        f"неверный --bp '{text}': ожидаются номера строк через запятую",
                        code=CODE_PROJECT,
                        source=SOURCE_DEBUG,
                        suggestion="например --bp Module.bsl:5,9",
                    )
                )
                bad = True
                break
            lines.append(int(part))
        if bad or not lines:
            continue
        merged.setdefault(path_part, []).extend(lines)

    specs: list[BreakpointCliSpec] = []
    for path, lines in merged.items():
        seen: set[int] = set()
        uniq: list[int] = []
        for line in lines:
            if line not in seen:
                seen.add(line)
                uniq.append(line)
        specs.append(BreakpointCliSpec(file=path, lines=tuple(uniq)))
    return specs, diagnostics


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
        # Targets are attached once by the ping daemon; it re-sends BP from
        # session.json on every new target. Never force re-attach (spike #135).
        session.ensure_targets_attached(force=False)
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
