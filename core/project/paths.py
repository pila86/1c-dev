"""Resolve scope root and default source/runtime paths (schema 1/2)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.project.constants import (
    DEFAULT_CONFIG_ID,
    HOME_DIR_NAME,
    HOME_MANIFEST_NAME,
    HOME_RUNTIME_DIR_NAME,
    LEGACY_RUNTIME_DIR_NAME,
)


def is_home_manifest(manifest_path: Path) -> bool:
    """True if path is ``<scope>/.1c-dev/project.yaml``."""
    resolved = manifest_path.resolve()
    return (
        resolved.name == HOME_MANIFEST_NAME and resolved.parent.name == HOME_DIR_NAME
    )


def scope_root_from_manifest(manifest_path: Path) -> Path:
    """Scope root: parent of ``.1c-dev`` for home layout, else manifest parent."""
    resolved = manifest_path.resolve()
    if is_home_manifest(resolved):
        return resolved.parent.parent
    return resolved.parent


def project_home(scope_root: Path) -> Path:
    """Project home directory under scope root."""
    return scope_root / HOME_DIR_NAME


def home_manifest_path(scope_root: Path) -> Path:
    """Absolute path to ``.1c-dev/project.yaml``."""
    return project_home(scope_root) / HOME_MANIFEST_NAME


def _pick_default_item(items: list[Any]) -> dict[str, Any] | None:
    marked: dict[str, Any] | None = None
    first: dict[str, Any] | None = None
    for item in items:
        if not isinstance(item, dict):
            continue
        if first is None:
            first = item
        if item.get("default") is True:
            marked = item
            break
    return marked if marked is not None else first


def default_configuration(data: dict[str, Any]) -> dict[str, Any] | None:
    """Default (or first) configuration entry for schema \"2\"."""
    configurations = data.get("configurations")
    if not isinstance(configurations, list):
        return None
    return _pick_default_item(configurations)


def default_runtime(data: dict[str, Any]) -> dict[str, Any] | None:
    """Default (or first) runtime entry for schema \"2\"."""
    runtimes = data.get("runtimes")
    if not isinstance(runtimes, list):
        return None
    return _pick_default_item(runtimes)


def default_source_rel(data: dict[str, Any]) -> str:
    """Relative source.path from schema 1 or default configuration (schema 2)."""
    if str(data.get("schema")) == "2":
        conf = default_configuration(data)
        if conf is not None:
            source = conf.get("source")
            if isinstance(source, dict):
                path = source.get("path")
                if isinstance(path, str) and path:
                    return path
        return "src/cf"
    source_raw = data.get("source")
    source_v1: dict[str, Any] = source_raw if isinstance(source_raw, dict) else {}
    return str(source_v1.get("path") or "src/cf")


def default_source_format(data: dict[str, Any]) -> str | None:
    """source.format from schema 1 or default configuration (schema 2)."""
    if str(data.get("schema")) == "2":
        conf = default_configuration(data)
        if conf is not None:
            source = conf.get("source")
            if isinstance(source, dict):
                fmt = source.get("format")
                return str(fmt) if fmt is not None else None
        return None
    source_raw = data.get("source")
    source_v1: dict[str, Any] = source_raw if isinstance(source_raw, dict) else {}
    fmt = source_v1.get("format")
    return str(fmt) if fmt is not None else None


def default_runtime_rel(data: dict[str, Any]) -> str:
    """Relative runtime.path from schema 1 or default runtime (schema 2)."""
    if str(data.get("schema")) == "2":
        rt = default_runtime(data)
        if rt is not None:
            path = rt.get("path")
            if isinstance(path, str) and path:
                return path
        conf = default_configuration(data)
        conf_id = DEFAULT_CONFIG_ID
        if conf is not None:
            raw_id = conf.get("id")
            if isinstance(raw_id, str) and raw_id:
                conf_id = raw_id
        return f"{HOME_RUNTIME_DIR_NAME}/{conf_id}"
    runtime_raw = data.get("runtime")
    runtime: dict[str, Any] = runtime_raw if isinstance(runtime_raw, dict) else {}
    return str(runtime.get("path") or f"{LEGACY_RUNTIME_DIR_NAME}/ib")


def default_runtime_type(data: dict[str, Any]) -> str:
    """runtime.type from schema 1 or default runtime (schema 2)."""
    if str(data.get("schema")) == "2":
        rt = default_runtime(data)
        if rt is not None:
            raw = rt.get("type")
            if isinstance(raw, str) and raw:
                return raw
        return "file"
    runtime_raw = data.get("runtime")
    runtime: dict[str, Any] = runtime_raw if isinstance(runtime_raw, dict) else {}
    return str(runtime.get("type") or "file")


def runtimes_summary(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Compact runtimes list for project.get (schema 2) or single runtime (schema 1)."""
    if str(data.get("schema")) == "2":
        runtimes = data.get("runtimes")
        if not isinstance(runtimes, list):
            return []
        out: list[dict[str, Any]] = []
        for rt in runtimes:
            if not isinstance(rt, dict):
                continue
            entry: dict[str, Any] = {}
            for key in ("id", "configuration", "type", "path", "default"):
                if key in rt:
                    entry[key] = rt[key]
            if entry:
                out.append(entry)
        return out

    runtime_raw = data.get("runtime")
    if not isinstance(runtime_raw, dict):
        return []
    entry = {
        "id": "default",
        "type": runtime_raw.get("type", "file"),
        "path": runtime_raw.get("path", f"{LEGACY_RUNTIME_DIR_NAME}/ib"),
        "default": True,
    }
    return [entry]
