"""Register configuration (+ runtime) in a schema-2 manifest (ADR-027 / ADR-028)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from core.diagnostics import Diagnostic, error
from core.project.constants import HOME_RUNTIME_DIR_NAME
from core.project.init import sanitize_project_name

CODE_CONF_EXISTS = "1CC001"


@dataclass
class RegisterResult:
    """In-memory registration of conf (+ optional runtime); caller writes manifest."""

    status: str  # "ok" | "error"
    config_id: str = ""
    source_rel: str = ""
    runtime_rel: str | None = None
    created: list[str] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)


def register_configuration_entry(
    data: dict[str, Any],
    root: Path,
    *,
    config_id: str | None = None,
    name: str | None = None,
    source_path: str | None = None,
    set_default: bool | None = None,
    with_runtime: bool = True,
) -> RegisterResult:
    """
    Append ``configurations[]`` (+ optional ``runtimes[]``) to ``data`` in place.

    Creates source and runtime directories on disk but does **not** scaffold XML
    and does **not** write the manifest file.
    """
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
            return RegisterResult(
                status="error",
                config_id=resolved_id,
                source_rel=resolved_path,
                diagnostics=[
                    error(
                        f"Configuration уже есть в манифесте: id={resolved_id!r}",
                        code=CODE_CONF_EXISTS,
                        suggestion="Укажите другой --id или configuration remove",
                    )
                ],
            )

    created: list[str] = []
    source_dir = root / resolved_path
    source_dir.mkdir(parents=True, exist_ok=True)
    rel_src = str(source_dir.relative_to(root))
    if rel_src not in created:
        created.append(rel_src)

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

    runtime_rel: str | None = None
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

    return RegisterResult(
        status="ok",
        config_id=resolved_id,
        source_rel=resolved_path,
        runtime_rel=runtime_rel,
        created=created,
    )


def write_manifest_yaml(manifest_path: Path, data: dict[str, Any]) -> None:
    """Write schema-2 project manifest as YAML."""
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
