"""Import orchestration: .cf → XML source / load into IB (ADR-015)."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from adapters.platform import DiscoveryResult, discover_environment
from adapters.platform_ibcmd import (
    IbcmdError,
    RunFn,
    import_cf_with_ibcmd,
    load_cf_with_ibcmd,
)
from adapters.platform_ibcmd.constants import CODE_IBCMD_FAILED, IBCMD_DATA_REL
from core.diagnostics import error
from core.import_cf.constants import (
    CODE_CF_MISSING,
    CODE_DIRTY_SOURCE,
    CODE_EXPORT_MISSING,
    CODE_IBCMD_MISSING,
    CODE_PROJECT,
)
from core.import_cf.result import ImportResult
from core.project.constants import MANIFEST_NAME
from core.project.detect import detect_manifest
from core.project.init import (
    default_project_name,
    platform_version_for_manifest,
    templates_root,
)
from core.project.load import load_manifest
from core.project.validate import validate_project

ImportFn = Callable[..., list[str]]
LoadFn = Callable[..., list[str]]

_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


def _render(template: str, values: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise KeyError(f"Неизвестный placeholder: {{{{{key}}}}}")
        return values[key]

    return _PLACEHOLDER_RE.sub(repl, template)


def _ensure_manifest(root: Path, *, discover: Callable[[], DiscoveryResult]) -> list[str]:
    """Create 1c.project.yaml + runtime dirs if missing. No AGENTS/XML skeleton."""
    created: list[str] = []
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        tmpl = templates_root() / "configuration" / "1c.project.yaml.tmpl"
        if not tmpl.is_file():
            raise FileNotFoundError(f"Шаблон манифеста не найден: {tmpl}")
        discovery = discover()
        platform_version = platform_version_for_manifest(discovery.platform.version)
        name = default_project_name(root)
        text = _render(
            tmpl.read_text(encoding="utf-8"),
            {
                "name": name,
                "platform_version": platform_version,
            },
        )
        manifest_path.write_text(text, encoding="utf-8", newline="\n")
        created.append(MANIFEST_NAME)

    for directory in (
        root / ".runtime",
        root / ".runtime" / "ib",
        root / "build",
    ):
        if not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)
            created.append(str(directory.relative_to(root)))

    return created


def _paths_from_manifest(
    data: dict[str, Any],
    root: Path,
) -> tuple[Path, Path, str, str]:
    source_raw = data.get("source")
    source: dict[str, Any] = source_raw if isinstance(source_raw, dict) else {}
    runtime_raw = data.get("runtime")
    runtime: dict[str, Any] = runtime_raw if isinstance(runtime_raw, dict) else {}
    source_rel = str(source.get("path") or "src/cf")
    runtime_rel = str(runtime.get("path") or ".runtime/ib")
    source_dir = (root / source_rel).resolve()
    db_path = (root / runtime_rel).resolve()
    return source_dir, db_path, source_rel, runtime_rel


def run_import(
    start: Path | None = None,
    *,
    from_path: Path | str,
    force: bool = False,
    run: RunFn | None = None,
    import_fn: ImportFn | None = None,
    discover: Callable[[], DiscoveryResult] | None = None,
) -> ImportResult:
    """
    Import .cf into project XML source (project.import).

    Creates manifest if missing; refuses dirty source without force.
    run / import_fn / discover: injectable for tests.
    """
    started = time.perf_counter()
    root = (start or Path.cwd()).resolve()
    discover_fn = discover or discover_environment
    cf_path = Path(from_path).expanduser().resolve()

    if not cf_path.is_file():
        return ImportResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            from_path=cf_path,
            diagnostics=[
                error(
                    f"Файл конфигурации не найден: {cf_path}",
                    code=CODE_CF_MISSING,
                    source="runtime",
                    suggestion="Укажите существующий путь к .cf через --from",
                )
            ],
        )

    try:
        created = _ensure_manifest(root, discover=discover_fn)
    except (OSError, FileNotFoundError, KeyError) as exc:
        return ImportResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            from_path=cf_path,
            diagnostics=[
                error(
                    f"Не удалось создать манифест проекта: {exc}",
                    code=CODE_PROJECT,
                    source="runtime",
                )
            ],
        )

    manifest_path = detect_manifest(root)
    if manifest_path is None:
        return ImportResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            from_path=cf_path,
            created=created,
            diagnostics=[
                error(
                    f"Файл {MANIFEST_NAME} не найден",
                    code=CODE_PROJECT,
                    source="runtime",
                )
            ],
        )

    data, load_diags = load_manifest(manifest_path)
    if data is None:
        return ImportResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=manifest_path.parent,
            from_path=cf_path,
            created=created,
            diagnostics=list(load_diags)
            or [
                error(
                    "Не удалось прочитать манифест",
                    code=CODE_PROJECT,
                    file=str(manifest_path.name),
                    source="runtime",
                )
            ],
        )

    root = manifest_path.parent
    source_dir, db_path, source_rel, _runtime_rel = _paths_from_manifest(data, root)
    data_path = (root / IBCMD_DATA_REL).resolve()

    fmt_raw = data.get("source")
    fmt = fmt_raw.get("format") if isinstance(fmt_raw, dict) else None
    if fmt is not None and fmt != "xml":
        return ImportResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            from_path=cf_path,
            source_path=source_dir,
            runtime_path=db_path,
            created=created,
            diagnostics=[
                error(
                    f"source.format={fmt!r}: import поддерживает только xml",
                    code=CODE_PROJECT,
                    file=manifest_path.name,
                    source="runtime",
                )
            ],
        )

    cfg_xml = source_dir / "Configuration.xml"
    if cfg_xml.is_file() and not force:
        return ImportResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            from_path=cf_path,
            source_path=source_dir,
            runtime_path=db_path,
            created=created,
            diagnostics=[
                error(
                    f"Исходники уже существуют: {source_rel}/Configuration.xml",
                    code=CODE_DIRTY_SOURCE,
                    file=f"{source_rel}/Configuration.xml",
                    source="runtime",
                    suggestion="Укажите --force для перезаписи или выберите пустой source.path",
                )
            ],
        )

    discovery = discover_fn()
    ibcmd_info = discovery.ibcmd
    if not ibcmd_info.found or ibcmd_info.path is None:
        return ImportResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            from_path=cf_path,
            source_path=source_dir,
            runtime_path=db_path,
            created=created,
            diagnostics=[
                error(
                    "ibcmd не найден",
                    code=CODE_IBCMD_MISSING,
                    source="platform",
                    suggestion=(
                        "Установите платформу 1С и добавьте ibcmd в PATH "
                        "(или в стандартный каталог установки)."
                    ),
                )
            ],
        )

    try:
        if import_fn is not None:
            steps = import_fn(
                ibcmd_info.path,
                db_path=db_path,
                data_path=data_path,
                cf_path=cf_path,
                source_dir=source_dir,
                run=run,
            )
        else:
            steps = import_cf_with_ibcmd(
                ibcmd_info.path,
                db_path=db_path,
                data_path=data_path,
                cf_path=cf_path,
                source_dir=source_dir,
                run=run,
            )
    except IbcmdError as exc:
        return ImportResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            from_path=cf_path,
            source_path=source_dir,
            runtime_path=db_path,
            created=created,
            steps=[],
            diagnostics=list(exc.diagnostics)
            or [
                error(
                    exc.message,
                    code=exc.code or CODE_IBCMD_FAILED,
                    source="platform",
                )
            ],
        )

    if not (source_dir / "Configuration.xml").is_file():
        return ImportResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            from_path=cf_path,
            source_path=source_dir,
            runtime_path=db_path,
            created=created,
            steps=list(steps),
            diagnostics=[
                error(
                    f"После export отсутствует {source_rel}/Configuration.xml",
                    code=CODE_EXPORT_MISSING,
                    source="runtime",
                    suggestion="Проверьте лог ibcmd config export",
                )
            ],
        )

    validation = validate_project(root)
    diags: list[Any] = []
    if validation.status != "ok":
        diags.extend(validation.diagnostics)

    return ImportResult(
        status="ok" if not diags else "failed",
        duration=time.perf_counter() - started,
        root=root,
        from_path=cf_path,
        source_path=source_dir,
        runtime_path=db_path,
        created=created,
        steps=list(steps),
        diagnostics=diags,
    )


def run_runtime_load(
    start: Path | None = None,
    *,
    from_path: Path | str,
    run: RunFn | None = None,
    load_fn: LoadFn | None = None,
    discover: Callable[[], DiscoveryResult] | None = None,
) -> ImportResult:
    """
    Load .cf into file IB without exporting XML (runtime.load).

    Manifest is required (same as build).
    """
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    discover_fn = discover or discover_environment
    cf_path = Path(from_path).expanduser().resolve()

    if not cf_path.is_file():
        return ImportResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=start_path,
            from_path=cf_path,
            diagnostics=[
                error(
                    f"Файл конфигурации не найден: {cf_path}",
                    code=CODE_CF_MISSING,
                    source="runtime",
                    suggestion="Укажите существующий путь к .cf через --from",
                )
            ],
        )

    manifest_path = detect_manifest(start_path)
    if manifest_path is None:
        return ImportResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=start_path,
            from_path=cf_path,
            diagnostics=[
                error(
                    f"Файл {MANIFEST_NAME} не найден",
                    code=CODE_PROJECT,
                    source="runtime",
                    suggestion="Выполните 1c-dev init или project import",
                )
            ],
        )

    data, load_diags = load_manifest(manifest_path)
    if data is None:
        return ImportResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=manifest_path.parent,
            from_path=cf_path,
            diagnostics=list(load_diags)
            or [
                error(
                    "Не удалось прочитать манифест",
                    code=CODE_PROJECT,
                    file=str(manifest_path.name),
                    source="runtime",
                )
            ],
        )

    root = manifest_path.parent
    _source_dir, db_path, _source_rel, _runtime_rel = _paths_from_manifest(data, root)
    data_path = (root / IBCMD_DATA_REL).resolve()

    discovery = discover_fn()
    ibcmd_info = discovery.ibcmd
    if not ibcmd_info.found or ibcmd_info.path is None:
        return ImportResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            from_path=cf_path,
            runtime_path=db_path,
            diagnostics=[
                error(
                    "ibcmd не найден",
                    code=CODE_IBCMD_MISSING,
                    source="platform",
                    suggestion=(
                        "Установите платформу 1С и добавьте ibcmd в PATH "
                        "(или в стандартный каталог установки)."
                    ),
                )
            ],
        )

    try:
        if load_fn is not None:
            steps = load_fn(
                ibcmd_info.path,
                db_path=db_path,
                data_path=data_path,
                cf_path=cf_path,
                run=run,
            )
        else:
            steps = load_cf_with_ibcmd(
                ibcmd_info.path,
                db_path=db_path,
                data_path=data_path,
                cf_path=cf_path,
                run=run,
            )
    except IbcmdError as exc:
        return ImportResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            from_path=cf_path,
            runtime_path=db_path,
            steps=[],
            diagnostics=list(exc.diagnostics)
            or [
                error(
                    exc.message,
                    code=exc.code or CODE_IBCMD_FAILED,
                    source="platform",
                )
            ],
        )

    return ImportResult(
        status="ok",
        duration=time.perf_counter() - started,
        root=root,
        from_path=cf_path,
        runtime_path=db_path,
        steps=list(steps),
    )
