"""Add a configuration to an existing project scope (ADR-027 / #100)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from adapters.platform import discover_environment
from core.diagnostics import error
from core.project.constants import HOME_RUNTIME_DIR_NAME
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

CODE_CONF_EXISTS = "1CC001"
CODE_CONF_NOT_SCOPE = "1CC002"


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
    if not isinstance(configurations, list):
        configurations = []
        data["configurations"] = configurations

    runtimes = data.get("runtimes")
    if not isinstance(runtimes, list):
        runtimes = []
        data["runtimes"] = runtimes

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

    is_first_conf = len(configurations) == 0
    conf_default = set_default if set_default is not None else is_first_conf
    if conf_default:
        for item in configurations:
            if isinstance(item, dict):
                item.pop("default", None)

    conf_entry: dict[str, Any] = {
        "id": resolved_id,
        "type": "configuration",
        "source": {"format": "xml", "path": resolved_path},
    }
    if conf_default:
        conf_entry["default"] = True
    configurations.append(conf_entry)

    if with_runtime:
        is_first_rt = len(runtimes) == 0
        if is_first_rt or conf_default:
            for item in runtimes:
                if isinstance(item, dict):
                    item.pop("default", None)
        runtime_rel = f"{HOME_RUNTIME_DIR_NAME}/{resolved_id}"
        runtime_dir = root / runtime_rel
        runtime_dir.mkdir(parents=True, exist_ok=True)
        rel_rt = str(runtime_dir.relative_to(root))
        if rel_rt not in created:
            created.append(rel_rt)
        rt_entry: dict[str, Any] = {
            "id": resolved_id,
            "configuration": resolved_id,
            "type": "file",
            "path": runtime_rel,
        }
        if is_first_rt or conf_default:
            rt_entry["default"] = True
        runtimes.append(rt_entry)

        # Default publish profile for the first runtime (matches historical init tmpl).
        if is_first_rt and "publish" not in data:
            data["publish"] = {
                "default": "local-ibsrv",
                "profiles": {
                    "local-ibsrv": {
                        "backend": "ibsrv",
                        "port": 8314,
                        "runtime": resolved_id,
                        "config": ".1c-dev/publish/local-ibsrv/ibsrv.yaml",
                    }
                },
            }

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
