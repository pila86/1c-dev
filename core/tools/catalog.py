"""Load shipped tool recipes from catalog/ (ADR-033)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ToolRecipe:
    """Parsed catalog/<id>/tool.yaml."""

    id: str
    name: str
    version: str
    mcp_name: str
    scope: str
    lifecycle: str
    raw: dict[str, Any]
    recipe_dir: Path

    @property
    def runtime(self) -> dict[str, Any]:
        value = self.raw.get("runtime")
        return value if isinstance(value, dict) else {}

    @property
    def interface(self) -> dict[str, Any]:
        value = self.raw.get("interface")
        return value if isinstance(value, dict) else {}

    @property
    def healthcheck(self) -> dict[str, Any]:
        value = self.raw.get("healthcheck")
        return value if isinstance(value, dict) else {}

    @property
    def agent(self) -> dict[str, Any]:
        value = self.raw.get("agent")
        return value if isinstance(value, dict) else {}

    @property
    def compose_file(self) -> str:
        return str(self.runtime.get("file") or "compose.yaml")

    @property
    def project_name(self) -> str:
        return str(self.runtime.get("project_name") or f"1c-dev-{self.id}")

    @property
    def profiles(self) -> list[str]:
        profiles = self.runtime.get("profiles")
        if isinstance(profiles, list):
            return [str(p) for p in profiles]
        return []

    @property
    def mcp_url_template(self) -> str:
        return str(self.interface.get("url") or "")

    @property
    def health_url_template(self) -> str:
        return str(self.healthcheck.get("url") or "")

    @property
    def guidance_rel(self) -> str | None:
        path = self.agent.get("guidance")
        return str(path) if path else None


def _package_roots() -> list[Path]:
    """Candidate roots that may contain catalog/ (repo or wheel layout)."""
    here = Path(__file__).resolve()
    return [
        here.parents[2],  # monorepo: core/tools → repo root
        here.parents[3],  # installed: site-packages adjacent layout
        Path.cwd(),
    ]


def catalog_root() -> Path:
    """Resolve shipped catalog directory."""
    for root in _package_roots():
        candidate = root / "catalog"
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(
        "catalog/ не найден (ожидается рядом с пакетом или в корне monorepo)"
    )


def list_catalog() -> list[str]:
    """Sorted tool ids present in shipped catalog."""
    root = catalog_root()
    ids: list[str] = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "tool.yaml").is_file():
            ids.append(child.name)
    return ids


def load_recipe(tool_id: str) -> ToolRecipe:
    """Load and validate minimal recipe fields for tool_id."""
    recipe_dir = catalog_root() / tool_id
    manifest = recipe_dir / "tool.yaml"
    if not manifest.is_file():
        raise FileNotFoundError(f"tool.yaml не найден для {tool_id}: {manifest}")
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"tool.yaml должен быть mapping: {manifest}")
    rid = str(data.get("id") or tool_id)
    if rid != tool_id:
        raise ValueError(f"id в tool.yaml ({rid}) не совпадает с каталогом ({tool_id})")
    return ToolRecipe(
        id=rid,
        name=str(data.get("name") or rid),
        version=str(data.get("version") or "0.0.0"),
        mcp_name=str(data.get("mcp_name") or rid),
        scope=str(data.get("scope") or "user"),
        lifecycle=str(data.get("lifecycle") or "managed"),
        raw=data,
        recipe_dir=recipe_dir,
    )
