"""Get one configuration with linked runtimes (#100)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.diagnostics import error
from core.project.detect import detect_manifest
from core.project.load import load_manifest
from core.project.paths import project_home, scope_root_from_manifest
from core.project.result import ProjectResult

CODE_CONF_UNKNOWN = "1CC003"


def get_configuration(
    start: Path | None = None,
    *,
    config_id: str,
) -> ProjectResult:
    """Return details for one configuration and its linked runtimes."""
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

    selected: dict[str, Any] | None = None
    for conf in configurations:
        if isinstance(conf, dict) and conf.get("id") == config_id:
            selected = conf
            break

    if selected is None:
        known = [
            str(c.get("id"))
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
                    suggestion=f"Доступные id: {', '.join(known) or '(нет)'}",
                )
            ],
        )

    linked: list[dict[str, Any]] = []
    runtimes = data.get("runtimes")
    if isinstance(runtimes, list):
        for rt in runtimes:
            if isinstance(rt, dict) and rt.get("configuration") == config_id:
                linked.append(rt)

    # Reuse ProjectResult.manifest as a focused payload via to_payload(include_manifest).
    focused = {
        "configuration": selected,
        "runtimes": linked,
    }
    return ProjectResult(
        status="ok",
        path=manifest_path,
        root=root,
        home=project_home(root),
        manifest=focused,
        runtimes=[
            {
                "id": rt.get("id"),
                "type": rt.get("type"),
                "path": rt.get("path"),
                "default": rt.get("default") is True,
            }
            for rt in linked
        ],
    )
