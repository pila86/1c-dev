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

    @property
    def service_enabled(self) -> bool:
        service = self.raw.get("service")
        if isinstance(service, dict):
            return bool(service.get("enabled", True))
        return self.lifecycle == "managed"

    @property
    def is_scaffold(self) -> bool:
        """True when recipe is a stub (Этап 3 scaffold) — install may soft-fail pins."""
        return bool(self.raw.get("scaffold"))

    @property
    def pin_keys(self) -> list[str]:
        """Env keys that must be pinned (tag/digest) before install.

        Declared via ``source.pins`` / ``source.images`` keys, else inferred as
        ``*_IMAGE`` entries in env.default at validation time.
        """
        source = self.raw.get("source")
        if not isinstance(source, dict):
            return []
        pins = source.get("pins")
        if isinstance(pins, list):
            return [str(p) for p in pins]
        images = source.get("images")
        if isinstance(images, dict):
            return [str(k) for k in images]
        if isinstance(images, list):
            return [str(p) for p in images]
        return []

    @property
    def source_type(self) -> str:
        source = self.raw.get("source")
        if isinstance(source, dict):
            return str(source.get("type") or "")
        return ""

    @property
    def compose_build(self) -> bool:
        """True when compose images are built from source (not pulled)."""
        if self.runtime.get("build") is True:
            return True
        return self.source_type == "git"

    @property
    def index_config(self) -> dict[str, Any]:
        value = self.raw.get("index")
        return value if isinstance(value, dict) else {}


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
