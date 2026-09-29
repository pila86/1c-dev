"""Add a configuration to an existing project scope (ADR-027 / #100)."""

from __future__ import annotations

from pathlib import Path

from adapters.platform import discover_environment
from core.configuration.register import (
    CODE_CONF_EXISTS,
    register_configuration_entry,
    write_manifest_yaml,
)
from core.diagnostics import error
from core.project.detect import detect_manifest
from core.project.init import (
    _scaffold_configuration_sources,
    platform_version_for_manifest,
    sanitize_project_name,
)
from core.project.load import load_manifest
from core.project.paths import project_home, scope_root_from_manifest
from core.project.result import ProjectResult
from core.project.validate import validate_project

CODE_CONF_NOT_SCOPE = "1CC002"

# Re-export for callers/tests that imported CODE_CONF_EXISTS from add.
__all__ = ["CODE_CONF_EXISTS", "CODE_CONF_NOT_SCOPE", "add_configuration"]


def add_configuration(
    start: Path | None = None,
    *,
    config_id: str | None = None,
    name: str | None = None,
    source_path: str | None = None,
    set_default: bool | None = None,
    with_runtime: bool = True,
    force: bool = False,
) -> ProjectResult:
    """
    Scaffold XML under ``src/<id>/`` (or ``--path``) and append to ``configurations[]``.

    Creates a linked runtime under ``.1c-dev/runtime/<id>`` when ``with_runtime``
    (default). First configuration / runtime gets ``default: true`` unless overridden.
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
                    "configuration add требует манифест schema \"2\"",
                    code=CODE_CONF_NOT_SCOPE,
                    suggestion="Используйте .1c-dev/project.yaml (schema 2)",
                )
            ],
        )

    resolved_name = sanitize_project_name(name or config_id or "Configuration")
    resolved_id = sanitize_project_name(config_id or resolved_name)
    resolved_path = (source_path or f"src/{resolved_id}").replace("\\", "/").strip("/")

    configurations = data.get("configurations")
    if isinstance(configurations, list):
        for item in configurations:
            if isinstance(item, dict) and item.get("id") == resolved_id:
                return ProjectResult(
                    status="error",
                    path=manifest_path,
                    root=root,
                    home=project_home(root),
                    diagnostics=[
                        error(
                            f"Configuration уже есть в манифесте: id={resolved_id!r}",
                            code=CODE_CONF_EXISTS,
                            suggestion="Укажите другой --id или --force после remove",
                        )
                    ],
                )

    discovery = discover_environment()
    platform_version = platform_version_for_manifest(discovery.platform.version)

    try:
        created = _scaffold_configuration_sources(
            root,
            source_rel=resolved_path,
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
                    f"Ошибка scaffold конфигурации: {exc}",
                    code="1CP006",
                )
            ],
        )

    reg = register_configuration_entry(
        data,
        root,
        config_id=resolved_id,
        name=resolved_name,
        source_path=resolved_path,
        set_default=set_default,
        with_runtime=with_runtime,
    )
    if reg.status != "ok":
        return ProjectResult(
            status="error",
            path=manifest_path,
            root=root,
            home=project_home(root),
            diagnostics=list(reg.diagnostics),
        )

    for item in reg.created:
        if item not in created:
            created.append(item)

    try:
        write_manifest_yaml(manifest_path, data)
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
