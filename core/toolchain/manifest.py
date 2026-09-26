"""Load toolchain/manifest.yaml (ADR-013)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ComponentSpec:
    """One toolchain component from the manifest."""

    id: str
    artifact: str
    pin: str
    source: dict[str, Any]
    min_java: int | None = None
    env: str | None = None
    status: str | None = None
    sha256: str | None = None

    @property
    def deferred(self) -> bool:
        return (self.status or "").lower() == "deferred"


@dataclass(frozen=True)
class ToolchainManifest:
    """Parsed toolchain manifest."""

    version: int
    components: tuple[ComponentSpec, ...]

    def get(self, component_id: str) -> ComponentSpec | None:
        for item in self.components:
            if item.id == component_id:
                return item
        return None


def _package_roots() -> list[Path]:
    """Candidate roots that may contain toolchain/ (repo or installed wheel layout)."""
    here = Path(__file__).resolve()
    return [
        here.parents[2],  # monorepo: core/toolchain → repo root
        here.parents[3],  # installed: site-packages adjacent layout
        Path.cwd(),
    ]


def manifest_path() -> Path:
    """Resolve path to toolchain/manifest.yaml."""
    for root in _package_roots():
        candidate = root / "toolchain" / "manifest.yaml"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("toolchain/manifest.yaml не найден рядом с установкой 1c-dev")


def load_manifest(path: Path | None = None) -> ToolchainManifest:
    """Parse toolchain manifest YAML into ComponentSpec list."""
    target = path if path is not None else manifest_path()
    raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Некорректный манифест toolchain: {target}")
    version = int(raw.get("version", 1))
    components_raw = raw.get("components") or []
    if not isinstance(components_raw, list):
        raise ValueError(f"components должен быть списком: {target}")
    components: list[ComponentSpec] = []
    for item in components_raw:
        if not isinstance(item, dict):
            continue
        cid = str(item["id"])
        components.append(
            ComponentSpec(
                id=cid,
                artifact=str(item["artifact"]),
                pin=str(item.get("pin", "")),
                source=dict(item.get("source") or {}),
                min_java=int(item["min_java"]) if item.get("min_java") is not None else None,
                env=str(item["env"]) if item.get("env") else None,
                status=str(item["status"]) if item.get("status") else None,
                sha256=str(item["sha256"]) if item.get("sha256") else None,
            )
        )
    return ToolchainManifest(version=version, components=tuple(components))
