"""Add an extension to an existing configuration project (ADR-023 / #88)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from adapters.platform import discover_environment
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
SUPPORTED_PURPOSES = frozenset({"product", "tests", "other"})


def add_extension(
    start: Path | None = None,
    *,
    ext_id: str | None = None,
    name: str | None = None,
    purpose: str = "product",
    config_id: str | None = None,
    force: bool = False,
) -> ProjectResult:
    """
    Scaffold ``src/cfe/<id>/`` and append to ``configurations[].extensions[]``.

    Requires an existing schema \"2\" configuration project.
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

    resolved_id = sanitize_ext_id(ext_id or name or "custom")
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

    discovery = discover_environment()
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
                "source": {"format": "xml", "path": f"src/cfe/{resolved_id}"},
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
