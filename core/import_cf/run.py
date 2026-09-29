"""Import orchestration: .cf → XML source / load into IB (ADR-015 / ADR-028)."""

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
from core.break_support.strip import strip_parent_configurations
from core.configuration.register import (
    register_configuration_entry,
    write_manifest_yaml,
)
from core.diagnostics import error
from core.import_cf.constants import (
    CODE_CF_MISSING,
    CODE_DIRTY_SOURCE,
    CODE_EXPORT_MISSING,
    CODE_IBCMD_MISSING,
    CODE_PROJECT,
)
from core.import_cf.result import ImportResult
from core.project.constants import (
    DEFAULT_CONFIG_ID,
    HOME_MANIFEST_REL,
    HOME_RUNTIME_DIR_NAME,
)
from core.project.detect import detect_manifest
from core.project.init import (
    default_project_name,
    platform_version_for_manifest,
    sanitize_project_name,
    templates_root,
)
from core.project.load import load_manifest
from core.project.paths import (
    home_manifest_path,
    project_home,
    scope_root_from_manifest,
)
from core.project.resolve import resolve_config_runtime
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


def _ensure_empty_scope(
    root: Path,
    *,
    discover: Callable[[], DiscoveryResult],
) -> list[str]:
    """Create empty ``.1c-dev/project.yaml`` + dirs if missing. No AGENTS/XML."""
    created: list[str] = []
    existing = detect_manifest(root)
    if existing is None:
        tmpl = templates_root() / "configuration" / "1c.project.empty.yaml.tmpl"
        if not tmpl.is_file():
            raise FileNotFoundError(f"Шаблон empty-манифеста не найден: {tmpl}")
        discovery = discover()
        platform_version = platform_version_for_manifest(discovery.platform.version)
        name = default_project_name(root)
        project_home(root).mkdir(parents=True, exist_ok=True)
        manifest_path = home_manifest_path(root)
        text = _render(
            tmpl.read_text(encoding="utf-8"),
            {
                "name": name,
                "platform_version": platform_version,
            },
        )
        manifest_path.write_text(text, encoding="utf-8", newline="\n")
        created.append(HOME_MANIFEST_REL)

    for directory in (
        root / HOME_RUNTIME_DIR_NAME,
        root / "build",
    ):
        if not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)
            created.append(str(directory.relative_to(root)))

    return created


def _conf_ids(data: dict[str, Any]) -> set[str]:
    configurations = data.get("configurations")
    if not isinstance(configurations, list):
        return set()
    ids: set[str] = set()
    for item in configurations:
        if isinstance(item, dict):
            conf_id = item.get("id")
            if isinstance(conf_id, str) and conf_id:
                ids.add(conf_id)
    return ids


def run_import(
    start: Path | None = None,
    *,
    from_path: Path | str,
    force: bool = False,
    break_support: bool = False,
    config_id: str | None = None,
    source_path: str | None = None,
    with_runtime: bool = True,
    run: RunFn | None = None,
    import_fn: ImportFn | None = None,
    discover: Callable[[], DiscoveryResult] | None = None,
) -> ImportResult:
    """
    Import .cf into configuration XML source (configuration.import).

    Ensures empty scope if missing; registers conf/runtime when needed
    (same path as configuration.add, without empty XML scaffold).
    break_support: strip ParentConfigurations* after export (ADR-020).
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
        created = _ensure_empty_scope(root, discover=discover_fn)
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
                    f"Манифест проекта не найден ({HOME_MANIFEST_REL})",
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
            root=scope_root_from_manifest(manifest_path),
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

    root = scope_root_from_manifest(manifest_path)
    existing_ids = _conf_ids(data)

    # Creating a new conf: explicit --id, or default "main" when scope has no confs.
    create_id: str | None = None
    if config_id is not None:
        want_id = sanitize_project_name(config_id)
        if want_id not in existing_ids:
            create_id = want_id
    elif not existing_ids:
        create_id = DEFAULT_CONFIG_ID

    if create_id is not None:
        reg = register_configuration_entry(
            data,
            root,
            config_id=create_id,
            source_path=source_path,
            with_runtime=with_runtime,
        )
        if reg.status != "ok":
            return ImportResult(
                status="failed",
                duration=time.perf_counter() - started,
                root=root,
                from_path=cf_path,
                created=created,
                diagnostics=list(reg.diagnostics),
            )
        for item in reg.created:
            if item not in created:
                created.append(item)
        try:
            write_manifest_yaml(manifest_path, data)
        except OSError as exc:
            return ImportResult(
                status="failed",
                duration=time.perf_counter() - started,
                root=root,
                from_path=cf_path,
                created=created,
                diagnostics=[
                    error(
                        f"Не удалось записать манифест: {exc}",
                        code=CODE_PROJECT,
                        source="runtime",
                    )
                ],
            )
        resolve_id: str | None = reg.config_id
    else:
        resolve_id = sanitize_project_name(config_id) if config_id else None

    target, resolve_diags = resolve_config_runtime(data, config_id=resolve_id)
    if target is None:
        return ImportResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            from_path=cf_path,
            created=created,
            diagnostics=list(resolve_diags)
            or [
                error(
                    "Не удалось выбрать configuration",
                    code=CODE_PROJECT,
                    source="runtime",
                    suggestion="Укажите --id или выполните configuration add",
                )
            ],
        )

    source_rel = target.source_rel
    source_dir = (root / source_rel).resolve()
    if target.runtime_rel:
        runtime_rel = target.runtime_rel
        db_path = (root / runtime_rel).resolve()
    else:
        runtime_rel = f"{HOME_RUNTIME_DIR_NAME}/{target.config_id}"
        db_path = (root / runtime_rel).resolve()
        db_path.mkdir(parents=True, exist_ok=True)
    data_path = (root / IBCMD_DATA_REL).resolve()

    fmt = target.source_format
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
                    suggestion=(
                        "Укажите --force для перезаписи или выберите пустой source.path"
                    ),
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

    removed: list[str] = []
    diags: list[Any] = []
    if break_support:
        removed, strip_diags = strip_parent_configurations(source_dir, root=root)
        diags.extend(strip_diags)

    validation = validate_project(root)
    if validation.status != "ok":
        diags.extend(validation.diagnostics)

    hard_diags = [d for d in diags if d.get("severity") == "error"]
    return ImportResult(
        status="ok" if not hard_diags else "failed",
        duration=time.perf_counter() - started,
        root=root,
        from_path=cf_path,
        source_path=source_dir,
        runtime_path=db_path,
        created=created,
        steps=list(steps),
        removed=removed,
        diagnostics=diags,
    )


def run_runtime_load(
    start: Path | None = None,
    *,
    from_path: Path | str,
    config_id: str | None = None,
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
                    f"Манифест проекта не найден ({HOME_MANIFEST_REL})",
                    code=CODE_PROJECT,
                    source="runtime",
                    suggestion="Выполните 1c-dev init или configuration import",
                )
            ],
        )

    data, load_diags = load_manifest(manifest_path)
    if data is None:
        return ImportResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=scope_root_from_manifest(manifest_path),
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

    root = scope_root_from_manifest(manifest_path)
    target, resolve_diags = resolve_config_runtime(data, config_id=config_id)
    if target is None or target.runtime_rel is None:
        return ImportResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            from_path=cf_path,
            diagnostics=list(resolve_diags)
            or [
                error(
                    "Не удалось выбрать runtime для load",
                    code=CODE_PROJECT,
                    source="runtime",
                    suggestion="Укажите --config или добавьте runtime через configuration add",
                )
            ],
        )

    db_path = (root / target.runtime_rel).resolve()
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
