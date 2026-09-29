"""Result types for project API."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from core.diagnostics import Diagnostic

Status = Literal["ok", "error"]


def build_scope_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    """Normalized scope composition for ``project.get`` / ``project.info`` (#100)."""
    configurations_out: list[dict[str, Any]] = []
    default_config: str | None = None
    configurations = manifest.get("configurations")
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
            is_default = conf.get("default") is True
            if is_default:
                default_config = conf_id
            configurations_out.append(
                {
                    "id": conf_id,
                    "path": path,
                    "default": is_default,
                    "extensions": ext_ids,
                }
            )

    runtimes_out: list[dict[str, Any]] = []
    default_runtime: str | None = None
    runtimes = manifest.get("runtimes")
    if isinstance(runtimes, list):
        for rt in runtimes:
            if not isinstance(rt, dict):
                continue
            rt_id = rt.get("id")
            if not isinstance(rt_id, str) or not rt_id:
                continue
            is_default = rt.get("default") is True
            if is_default:
                default_runtime = rt_id
            conf_ref = rt.get("configuration")
            rt_path = rt.get("path")
            runtimes_out.append(
                {
                    "id": rt_id,
                    "configuration": conf_ref if isinstance(conf_ref, str) else None,
                    "path": rt_path if isinstance(rt_path, str) else None,
                    "default": is_default,
                }
            )

    return {
        "configurations": configurations_out,
        "runtimes": runtimes_out,
        "defaults": {
            "configuration": default_config,
            "runtime": default_runtime,
        },
    }


@dataclass
class ProjectResult:
    """Structured result for project detect/validate/info/init/ide/list."""

    status: Status
    diagnostics: list[Diagnostic] = field(default_factory=list)
    path: Path | None = None
    root: Path | None = None
    home: Path | None = None
    manifest: dict[str, Any] | None = None
    runtimes: list[dict[str, Any]] = field(default_factory=list)
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def to_payload(self, *, include_manifest: bool = False) -> dict[str, Any]:
        """Machine-readable payload for CLI/MCP."""
        payload: dict[str, Any] = {"status": self.status}
        if self.path is not None:
            payload["path"] = str(self.path)
            payload["manifest_path"] = str(self.path)
        if self.root is not None:
            payload["root"] = str(self.root)
        if self.home is not None:
            payload["home"] = str(self.home)
        if self.runtimes:
            payload["runtimes"] = list(self.runtimes)
        if self.manifest is not None and "schema" in self.manifest:
            payload["summary"] = build_scope_summary(self.manifest)
        if include_manifest and self.manifest is not None:
            payload["manifest"] = self.manifest
        elif self.manifest is not None and self.status == "ok" and not include_manifest:
            # detect: краткие поля, если манифест распарсен
            project = self.manifest.get("project")
            if isinstance(project, dict):
                payload["project"] = {
                    k: project[k] for k in ("name", "type") if k in project
                }
        if self.created:
            payload["created"] = list(self.created)
        if self.updated:
            payload["updated"] = list(self.updated)
        if self.skipped:
            payload["skipped"] = list(self.skipped)
        if self.diagnostics:
            payload["diagnostics"] = list(self.diagnostics)
        return payload
