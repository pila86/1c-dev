"""List configurations in a project scope (#100)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.diagnostics import Diagnostic, error
from core.project.detect import detect_manifest
from core.project.load import load_manifest
from core.project.paths import scope_root_from_manifest

Status = str  # "ok" | "error"


@dataclass
class ConfigurationListResult:
    """Brief list of configurations in the scope."""

    status: Status
    diagnostics: list[Diagnostic] = field(default_factory=list)
    root: Path | None = None
    path: Path | None = None
    configurations: list[dict[str, Any]] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": self.status}
        if self.root is not None:
            payload["root"] = str(self.root)
        if self.path is not None:
            payload["path"] = str(self.path)
            payload["manifest_path"] = str(self.path)
        payload["configurations"] = list(self.configurations)
        if self.diagnostics:
            payload["diagnostics"] = list(self.diagnostics)
        return payload


def list_configurations(start: Path | None = None) -> ConfigurationListResult:
    """Return a short list of configurations (id, path, default, extensions)."""
    start_path = (start or Path.cwd()).resolve()
    manifest_path = detect_manifest(start_path)
    if manifest_path is None:
        return ConfigurationListResult(
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
        return ConfigurationListResult(
            status="error",
            path=manifest_path,
            root=root,
            diagnostics=list(load_diags)
            or [error("Не удалось прочитать манифест", code="1CP002")],
        )

    items: list[dict[str, Any]] = []
    configurations = data.get("configurations")
    if isinstance(configurations, list):
        for conf in configurations:
            if not isinstance(conf, dict):
                continue
            conf_id = conf.get("id")
            if not isinstance(conf_id, str) or not conf_id:
                continue
            source = conf.get("source")
            path = ""
            if isinstance(source, dict):
                raw = source.get("path")
                if isinstance(raw, str):
                    path = raw
            ext_ids: list[str] = []
            extensions = conf.get("extensions")
            if isinstance(extensions, list):
                for ext in extensions:
                    if isinstance(ext, dict) and isinstance(ext.get("id"), str):
                        ext_ids.append(ext["id"])
            items.append(
                {
                    "id": conf_id,
                    "path": path,
                    "default": conf.get("default") is True,
                    "type": conf.get("type"),
                    "extensions": ext_ids,
                }
            )

    return ConfigurationListResult(
        status="ok",
        path=manifest_path,
        root=root,
        configurations=items,
    )
