"""Set default configuration in the manifest (#100)."""

from __future__ import annotations

from pathlib import Path

import yaml

from core.configuration.get import CODE_CONF_UNKNOWN
from core.diagnostics import error
from core.project.detect import detect_manifest
from core.project.load import load_manifest
from core.project.paths import project_home, scope_root_from_manifest
from core.project.result import ProjectResult
from core.project.validate import validate_project


def set_default_configuration(
    start: Path | None = None,
    *,
    config_id: str,
) -> ProjectResult:
    """Mark ``config_id`` as the sole ``default: true`` configuration."""
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
                    suggestion="Выполните 1c-dev init",
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
            or [error("Не удалось прочитать манифест", code="1CP002")],
        )

    configurations = data.get("configurations")
    if not isinstance(configurations, list):
        configurations = []
        data["configurations"] = configurations

    found = False
    for conf in configurations:
        if not isinstance(conf, dict):
            continue
        if conf.get("id") == config_id:
            conf["default"] = True
            found = True
        else:
            conf.pop("default", None)

    if not found:
        known = [
            c.get("id")
            for c in configurations
            if isinstance(c, dict) and isinstance(c.get("id"), str)
        ]
        return ProjectResult(
            status="error",
            path=manifest_path,
            root=root,
            home=project_home(root),
            diagnostics=[
                error(
                    f"Неизвестная configuration id={config_id!r}",
                    code=CODE_CONF_UNKNOWN,
                    suggestion=f"Доступные id: {', '.join(str(k) for k in known) or '(нет)'}",
                )
            ],
        )

    # Align default runtime to first runtime of this configuration when present.
    runtimes = data.get("runtimes")
    if isinstance(runtimes, list):
        linked = [
            rt
            for rt in runtimes
            if isinstance(rt, dict) and rt.get("configuration") == config_id
        ]
        if linked:
            for rt in runtimes:
                if isinstance(rt, dict):
                    rt.pop("default", None)
            linked[0]["default"] = True

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
    result.updated = [str(manifest_path.relative_to(root))]
    return result
