"""Project desire-list: ``.1c-dev/tools.yaml`` (ADR-033 Этап 5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from core.diagnostics import Diagnostic, error, info, warning
from core.services.health import check_http
from core.tools.catalog import list_catalog, load_recipe
from core.tools.install import (
    expand_template,
    is_installed,
    load_installed_recipe,
    resolve_env_vars,
)

DESIRE_REL = Path(".1c-dev") / "tools.yaml"


@dataclass(frozen=True)
class DesireList:
    """Parsed project desire-list."""

    path: Path | None
    tool_ids: tuple[str, ...]

    @property
    def found(self) -> bool:
        return self.path is not None and self.path.is_file()


@dataclass
class DesireCheckItem:
    tool_id: str
    desired: bool
    installed: bool
    in_catalog: bool
    healthy: bool | None = None
    mcp_url: str | None = None
    status: str = "ok"  # ok | missing | unknown | degraded

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.tool_id,
            "desired": self.desired,
            "installed": self.installed,
            "inCatalog": self.in_catalog,
            "healthy": self.healthy,
            "mcpUrl": self.mcp_url,
            "status": self.status,
        }


@dataclass
class DesireCheckResult:
    desire_path: str | None
    items: list[DesireCheckItem] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    status: str = "ok"  # ok | error | degraded

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "desirePath": self.desire_path,
            "tools": [item.to_payload() for item in self.items],
            "diagnostics": list(self.diagnostics),
        }


def desire_path(project_root: Path) -> Path:
    return project_root / DESIRE_REL


def load_desire_list(project_root: Path) -> DesireList:
    """Load ``.1c-dev/tools.yaml`` if present.

    Schema::

        tools:
          - v8std
          - bsl-ls

    Also accepts top-level list or ``required: [...]``.
    """
    path = desire_path(project_root)
    if not path.is_file():
        return DesireList(path=None, tool_ids=())
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return DesireList(path=path, tool_ids=())
    ids = _parse_tool_ids(raw)
    return DesireList(path=path, tool_ids=tuple(ids))


def _parse_tool_ids(raw: object) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    if not isinstance(raw, dict):
        return []
    for key in ("tools", "required"):
        value = raw.get(key)
        if isinstance(value, list):
            return [str(x).strip() for x in value if str(x).strip()]
    return []


def check_desire_list(
    project_root: Path,
    *,
    probe_health: bool = True,
) -> DesireCheckResult:
    """Compare desire-list vs installed (+ optional health for managed HTTP)."""
    desire = load_desire_list(project_root)
    diags: list[Diagnostic] = []
    items: list[DesireCheckItem] = []
    catalog = set(list_catalog())

    if not desire.found:
        diags.append(
            info(
                f"{DESIRE_REL} отсутствует — desire-list не задан",
                code="1CX000",
                source="tools",
                suggestion="Создайте .1c-dev/tools.yaml со списком required tools",
            )
        )
        return DesireCheckResult(
            desire_path=None,
            items=[],
            diagnostics=diags,
            status="ok",
        )

    if not desire.tool_ids:
        diags.append(
            warning(
                f"{DESIRE_REL} пуст или не распознан (ожидается tools: [id, …])",
                code="1CX007",
                source="tools",
            )
        )
        return DesireCheckResult(
            desire_path=str(desire.path) if desire.path else None,
            items=[],
            diagnostics=diags,
            status="degraded",
        )

    overall: str = "ok"
    for tool_id in desire.tool_ids:
        in_catalog = tool_id in catalog
        installed = is_installed(tool_id)
        healthy: bool | None = None
        mcp_url: str | None = None
        status = "ok"

        if not in_catalog:
            status = "unknown"
            overall = "error" if overall != "error" else overall
            diags.append(
                error(
                    f"tool «{tool_id}» из desire-list нет в catalog",
                    code="1CX001",
                    source="tools",
                )
            )
        elif not installed:
            status = "missing"
            overall = "error"
            diags.append(
                error(
                    f"tool «{tool_id}» требуется desire-list, но не установлен",
                    code="1CX002",
                    source="tools",
                    suggestion=f"1c-dev tools install {tool_id}",
                )
            )
        else:
            try:
                recipe = load_installed_recipe(tool_id)
                env_vars = resolve_env_vars(recipe.recipe_dir)
                if recipe.mcp_url_template:
                    mcp_url = expand_template(recipe.mcp_url_template, env_vars)
                if (
                    probe_health
                    and recipe.lifecycle == "managed"
                    and recipe.service_enabled
                    and recipe.health_url_template
                ):
                    health_url = expand_template(recipe.health_url_template, env_vars)
                    healthy = check_http(health_url, timeout_sec=1.5).reachable
                    if not healthy:
                        status = "degraded"
                        if overall == "ok":
                            overall = "degraded"
                        diags.append(
                            warning(
                                f"tool «{tool_id}» установлен, но health unreachable",
                                code="1CX005",
                                source="tools",
                                suggestion=f"1c-dev services up {tool_id}",
                            )
                        )
            except (OSError, ValueError, FileNotFoundError):
                status = "degraded"
                if overall == "ok":
                    overall = "degraded"

        items.append(
            DesireCheckItem(
                tool_id=tool_id,
                desired=True,
                installed=installed,
                in_catalog=in_catalog,
                healthy=healthy,
                mcp_url=mcp_url,
                status=status,
            )
        )

    return DesireCheckResult(
        desire_path=str(desire.path) if desire.path else None,
        items=items,
        diagnostics=diags,
        status=overall,
    )


def guidance_tool_ids(project_root: Path | None = None) -> set[str]:
    """Tool ids that should get agent guidance: installed ∪ desire."""
    from core.tools.install import list_installed

    ids = set(list_installed())
    if project_root is not None:
        ids.update(load_desire_list(project_root).tool_ids)
    return ids


def load_guidance_body(tool_id: str) -> str | None:
    """Guidance text from installed recipe, else shipped catalog."""
    recipe = None
    if is_installed(tool_id):
        try:
            recipe = load_installed_recipe(tool_id)
        except (OSError, ValueError, FileNotFoundError):
            recipe = None
    if recipe is None:
        try:
            recipe = load_recipe(tool_id)
        except (OSError, ValueError, FileNotFoundError):
            return None
    rel = recipe.guidance_rel
    if not rel:
        return None
    path = recipe.recipe_dir / rel
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")
