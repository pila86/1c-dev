"""Add an extension to an existing configuration project (ADR-023 / #88 / #95)."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from adapters.platform import DiscoveryResult, discover_environment
from adapters.platform_ibcmd import IbcmdError, RunFn, import_cfe_with_ibcmd
from adapters.platform_ibcmd.constants import CODE_IBCMD_FAILED, IBCMD_DATA_REL
from core.diagnostics import error
from core.project.detect import detect_manifest
from core.project.init import (
    _scaffold_extension_sources,
    platform_version_for_manifest,
    sanitize_ext_id,
    sanitize_project_name,
)
from core.project.load import load_manifest
from core.project.paths import project_home, scope_root_from_manifest
from core.project.resolve import resolve_config_runtime
from core.project.result import ProjectResult
from core.project.validate import validate_project

CODE_EXT_EXISTS = "1CE001"
CODE_EXT_NOT_CONFIG = "1CE002"
CODE_CFE_MISSING = "1CE003"
CODE_IBCMD_MISSING = "1CE004"
SUPPORTED_PURPOSES = frozenset({"product", "tests", "other"})

# Scratch IB for .cfe → XML dump (not the project's default runtime).
CFE_IMPORT_RUNTIME_REL = ".1c-dev/runtime/_cfe-import"

ImportCfeFn = Callable[..., list[str]]


def add_extension(
    start: Path | None = None,
    *,
    ext_id: str | None = None,
    name: str | None = None,
    purpose: str = "product",
    config_id: str | None = None,
    force: bool = False,
    from_cfe: Path | str | None = None,
    run: RunFn | None = None,
    import_cfe_fn: ImportCfeFn | None = None,
    discover: Callable[[], DiscoveryResult] | None = None,
) -> ProjectResult:
    """
    Append to ``configurations[].extensions[]``.

    Default: scaffold ``src/cfe/<id>/`` (XML).
    With ``from_cfe``: load .cfe into a scratch IB → export hierarchical XML into
    ``src/cfe/<id>/`` (``source.format=xml``). Does not copy the binary .cfe into src.
    """
    start_path = (start or Path.cwd()).resolve()
    manifest_path = detect_manifest(start_path)
    if manifest_path is None:
        return ProjectResult(
            status="error",
            root=start_path,
            diagnostics=[
                error(
                    "Манифест проекта не найден",
                    code="1CP001",
                    suggestion="Выполните 1c-dev init, затем 1c-dev configuration add",
                )
            ],
        )

    root = scope_root_from_manifest(manifest_path)
    data, load_diags = load_manifest(manifest_path)
    if data is None:
        return ProjectResult(
            status="error",
            path=manifest_path,
            root=root,
            home=project_home(root),
            diagnostics=list(load_diags)
            or [
                error(
                    "Не удалось прочитать манифест",
                    code="1CP002",
                    file=str(manifest_path.name),
                )
            ],
        )

    if str(data.get("schema")) != "2":
        return ProjectResult(
            status="error",
            path=manifest_path,
            root=root,
            home=project_home(root),
            diagnostics=[
                error(
                    "extension add требует манифест schema \"2\"",
                    code=CODE_EXT_NOT_CONFIG,
                    suggestion="Используйте .1c-dev/project.yaml (schema 2)",
                )
            ],
        )

    configurations = data.get("configurations")
    if isinstance(configurations, list) and not configurations:
        return ProjectResult(
            status="error",
            path=manifest_path,
            root=root,
            home=project_home(root),
            diagnostics=[
                error(
                    "В манифесте нет configurations[] — сначала добавьте configuration",
                    code=CODE_EXT_NOT_CONFIG,
                    suggestion="Выполните 1c-dev configuration add",
                )
            ],
        )

    if purpose not in SUPPORTED_PURPOSES:
        return ProjectResult(
            status="error",
            path=manifest_path,
            root=root,
            home=project_home(root),
            diagnostics=[
                error(
                    f"Неизвестный purpose: {purpose}",
                    code="1CP005",
                    suggestion="Используйте product, tests или other",
                )
            ],
        )

    cfe_src: Path | None = None
    if from_cfe is not None and str(from_cfe).strip() != "":
        cfe_src = Path(from_cfe).expanduser().resolve()
        if not cfe_src.is_file():
            return ProjectResult(
                status="error",
                path=manifest_path,
                root=root,
                home=project_home(root),
                diagnostics=[
                    error(
                        f"Файл .cfe не найден: {cfe_src}",
                        code=CODE_CFE_MISSING,
                        suggestion="Укажите существующий путь через --from",
                    )
                ],
            )
        if cfe_src.suffix.lower() != ".cfe":
            return ProjectResult(
                status="error",
                path=manifest_path,
                root=root,
                home=project_home(root),
                diagnostics=[
                    error(
                        f"Ожидается файл .cfe, получено: {cfe_src.name}",
                        code=CODE_CFE_MISSING,
                        suggestion="Передайте путь к файлу расширения (.cfe)",
                    )
                ],
            )

    target, resolve_diags = resolve_config_runtime(
        data,
        config_id=config_id,
        require_runtime=False,
    )
    if target is None:
        return ProjectResult(
            status="error",
            path=manifest_path,
            root=root,
            home=project_home(root),
            diagnostics=list(resolve_diags),
        )

    conf = target.configuration
    if conf.get("type") != "configuration":
        return ProjectResult(
            status="error",
            path=manifest_path,
            root=root,
            home=project_home(root),
            diagnostics=[
                error(
                    "extension add применим только к configurations[].type=configuration",
                    code=CODE_EXT_NOT_CONFIG,
                    suggestion="Выберите --config с type configuration",
                )
            ],
        )

    default_stem = cfe_src.stem if cfe_src is not None else "custom"
    resolved_id = sanitize_ext_id(ext_id or name or default_stem)
    resolved_name = sanitize_project_name(name or ext_id or resolved_id)

    existing = conf.get("extensions")
    if isinstance(existing, list):
        for item in existing:
            if not isinstance(item, dict):
                continue
            if item.get("id") == resolved_id or item.get("name") == resolved_name:
                return ProjectResult(
                    status="error",
                    path=manifest_path,
                    root=root,
                    home=project_home(root),
                    diagnostics=[
                        error(
                            f"Расширение уже есть в манифесте: id={resolved_id!r} "
                            f"или name={resolved_name!r}",
                            code=CODE_EXT_EXISTS,
                            suggestion="Укажите другой --id/--name или --force",
                        )
                    ],
                )

    created: list[str] = []
    source_rel = f"src/cfe/{resolved_id}"
    source_dir = (root / source_rel).resolve()

    if cfe_src is not None:
        if source_dir.exists() and any(source_dir.iterdir()) and not force:
            return ProjectResult(
                status="error",
                path=manifest_path,
                root=root,
                home=project_home(root),
                diagnostics=[
                    error(
                        f"Каталог исходников уже существует: {source_rel}",
                        code="1CP004",
                        suggestion="Укажите --force для перезаписи XML из .cfe",
                    )
                ],
            )

        discovery = (discover or discover_environment)()
        ibcmd_info = discovery.ibcmd
        if not ibcmd_info.found or ibcmd_info.path is None:
            return ProjectResult(
                status="error",
                path=manifest_path,
                root=root,
                home=project_home(root),
                diagnostics=[
                    error(
                        "ibcmd не найден — нужен для выгрузки .cfe в XML",
                        code=CODE_IBCMD_MISSING,
                        source="platform",
                        suggestion=(
                            "Установите платформу 1С с ibcmd "
                            "или укажите path к ibcmd в PATH"
                        ),
                    )
                ],
            )

        if source_dir.exists() and force:
            shutil.rmtree(source_dir)
        source_dir.mkdir(parents=True, exist_ok=True)

        db_path = (root / CFE_IMPORT_RUNTIME_REL).resolve()
        data_path = (root / IBCMD_DATA_REL).resolve()
        importer = import_cfe_fn or import_cfe_with_ibcmd
        try:
            importer(
                ibcmd_info.path,
                db_path=db_path,
                data_path=data_path,
                cfe_path=cfe_src,
                source_dir=source_dir,
                extension=resolved_name,
                run=run,
            )
        except IbcmdError as exc:
            if source_dir.exists():
                shutil.rmtree(source_dir, ignore_errors=True)
            diags = list(exc.diagnostics) or [
                error(exc.message, code=exc.code, source="platform")
            ]
            for diag in diags:
                if diag.get("severity") == "error" and not diag.get("suggestion"):
                    diag["suggestion"] = (
                        "Имя --name должно совпадать с именем расширения внутри .cfe; "
                        "нужен ibcmd с support load/export --extension"
                    )
                    break
            return ProjectResult(
                status="error",
                path=manifest_path,
                root=root,
                home=project_home(root),
                diagnostics=diags,
            )
        except OSError as exc:
            if source_dir.exists():
                shutil.rmtree(source_dir, ignore_errors=True)
            return ProjectResult(
                status="error",
                path=manifest_path,
                root=root,
                home=project_home(root),
                diagnostics=[
                    error(f"Ошибка выгрузки .cfe в XML: {exc}", code="1CP006")
                ],
            )

        if not (source_dir / "Configuration.xml").is_file():
            shutil.rmtree(source_dir, ignore_errors=True)
            return ProjectResult(
                status="error",
                path=manifest_path,
                root=root,
                home=project_home(root),
                diagnostics=[
                    error(
                        "После export нет Configuration.xml — выгрузка .cfe не удалась",
                        code=CODE_IBCMD_FAILED,
                        source="platform",
                        suggestion=(
                            "Проверьте, что --name совпадает с именем в .cfe "
                            "и ibcmd поддерживает config load/export --extension"
                        ),
                    )
                ],
            )
        created.append(source_rel)
    else:
        discovery = (discover or discover_environment)()
        platform_version = platform_version_for_manifest(discovery.platform.version)

        try:
            created = _scaffold_extension_sources(
                root,
                ext_id=resolved_id,
                name=resolved_name,
                platform_version=platform_version,
                force=force,
            )
        except FileExistsError as exc:
            return ProjectResult(
                status="error",
                path=manifest_path,
                root=root,
                home=project_home(root),
                diagnostics=[
                    error(
                        str(exc),
                        code="1CP004",
                        suggestion="Укажите --force для перезаписи исходников",
                    )
                ],
            )
        except (OSError, FileNotFoundError, KeyError) as exc:
            return ProjectResult(
                status="error",
                path=manifest_path,
                root=root,
                home=project_home(root),
                diagnostics=[
                    error(
                        f"Ошибка scaffold расширения: {exc}",
                        code="1CP006",
                    )
                ],
            )

    source_entry = {"format": "xml", "path": source_rel}

    # Patch configurations[].extensions[]
    configurations = data.get("configurations")
    if not isinstance(configurations, list):
        return ProjectResult(
            status="error",
            path=manifest_path,
            root=root,
            diagnostics=[error("configurations[] отсутствует", code="1CP002")],
        )

    patched = False
    for item in configurations:
        if not isinstance(item, dict):
            continue
        if item.get("id") != target.config_id:
            continue
        exts: list[Any] = list(item.get("extensions") or [])
        if not isinstance(item.get("extensions"), list):
            exts = []
        exts.append(
            {
                "id": resolved_id,
                "name": resolved_name,
                "purpose": purpose,
                "source": source_entry,
            }
        )
        item["extensions"] = exts
        patched = True
        break

    if not patched:
        return ProjectResult(
            status="error",
            path=manifest_path,
            root=root,
            diagnostics=[
                error(
                    f"Configuration {target.config_id!r} не найдена при записи",
                    code="1CP002",
                )
            ],
        )

    try:
        manifest_path.write_text(
            yaml.safe_dump(
                data,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            ),
            encoding="utf-8",
            newline="\n",
        )
    except OSError as exc:
        return ProjectResult(
            status="error",
            path=manifest_path,
            root=root,
            diagnostics=[
                error(f"Не удалось записать манифест: {exc}", code="1CP006")
            ],
        )

    result = validate_project(root)
    result.created = created
    result.updated = [str(manifest_path.relative_to(root))]
    return result
