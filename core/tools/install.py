"""Install / remove external tool recipes into XDG share (ADR-033)."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from core.diagnostics import Diagnostic, error, info, warning
from core.tools.catalog import ToolRecipe, list_catalog, load_recipe
from core.tools.paths import installed_tool_dir, tools_share_dir

ProgressCb = Callable[[str], None] | None
Status = Literal["ok", "error", "skipped"]


@dataclass
class InstallResult:
    """Result of tools install."""

    tool_id: str
    status: Status
    path: str | None = None
    pulled: bool = False
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "toolId": self.tool_id,
            "status": self.status,
            "path": self.path,
            "pulled": self.pulled,
            "diagnostics": list(self.diagnostics),
        }


@dataclass
class RemoveResult:
    """Result of tools remove."""

    tool_id: str
    status: Status
    removed: bool = False
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "toolId": self.tool_id,
            "status": self.status,
            "removed": self.removed,
            "diagnostics": list(self.diagnostics),
        }


@dataclass
class ToolInfo:
    """Catalog + install status for one tool."""

    id: str
    name: str
    version: str
    mcp_name: str
    installed: bool
    path: str | None
    lifecycle: str
    mcp_url: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "mcpName": self.mcp_name,
            "installed": self.installed,
            "path": self.path,
            "lifecycle": self.lifecycle,
            "mcpUrl": self.mcp_url,
        }


def is_installed(
    tool_id: str,
    *,
    env: dict[str, str] | None = None,
    platform: str | None = None,
) -> bool:
    dest = installed_tool_dir(tool_id, env=env, platform=platform)
    return (dest / "tool.yaml").is_file()


def list_installed(
    *,
    env: dict[str, str] | None = None,
    platform: str | None = None,
) -> list[str]:
    root = tools_share_dir(env=env, platform=platform)
    if not root.is_dir():
        return []
    ids: list[str] = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "tool.yaml").is_file():
            ids.append(child.name)
    return ids


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def resolve_env_vars(
    tool_dir: Path,
    *,
    environ: dict[str, str] | None = None,
) -> dict[str, str]:
    """Merge env.default + .env + process env for compose/url expansion.

    Process env overlays keys already present in recipe env files, plus
    ``COMPOSE_*``. Tool-specific prefixes (e.g. ``V8STD_``) are covered when
    those keys exist in env.default / .env.
    """
    merged: dict[str, str] = {}
    merged.update(_read_env_file(tool_dir / "env.default"))
    merged.update(_read_env_file(tool_dir / ".env"))
    known = set(merged.keys())
    base = environ if environ is not None else os.environ
    for key, value in base.items():
        if key in known or key.startswith("COMPOSE_"):
            merged[key] = value
    return merged


def expand_template(template: str, env_vars: dict[str, str]) -> str:
    """Expand ${VAR:-default} and ${VAR} in recipe URL templates."""
    import re

    def repl_default(match: re.Match[str]) -> str:
        key = match.group(1)
        default = match.group(2)
        return env_vars.get(key, default)

    def repl_plain(match: re.Match[str]) -> str:
        key = match.group(1)
        return env_vars.get(key, match.group(0))

    out = re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*):-([^}]*)}", repl_default, template)
    out = re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)}", repl_plain, out)
    return out


def load_installed_recipe(
    tool_id: str,
    *,
    env: dict[str, str] | None = None,
    platform: str | None = None,
) -> ToolRecipe:
    dest = installed_tool_dir(tool_id, env=env, platform=platform)
    manifest = dest / "tool.yaml"
    if not manifest.is_file():
        raise FileNotFoundError(tool_id)
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("invalid tool.yaml")
    return ToolRecipe(
        id=str(data.get("id") or tool_id),
        name=str(data.get("name") or tool_id),
        version=str(data.get("version") or "0.0.0"),
        mcp_name=str(data.get("mcp_name") or tool_id),
        scope=str(data.get("scope") or "user"),
        lifecycle=str(data.get("lifecycle") or "managed"),
        raw=data,
        recipe_dir=dest,
    )


def tool_info(
    tool_id: str,
    *,
    env: dict[str, str] | None = None,
    platform: str | None = None,
) -> ToolInfo:
    recipe = load_recipe(tool_id)
    installed = is_installed(tool_id, env=env, platform=platform)
    path = (
        str(installed_tool_dir(tool_id, env=env, platform=platform))
        if installed
        else None
    )
    mcp_url: str | None = None
    if installed and path is not None:
        env_vars = resolve_env_vars(Path(path), environ=env)
        if recipe.mcp_url_template:
            mcp_url = expand_template(recipe.mcp_url_template, env_vars)
    return ToolInfo(
        id=recipe.id,
        name=recipe.name,
        version=recipe.version,
        mcp_name=recipe.mcp_name,
        installed=installed,
        path=path,
        lifecycle=recipe.lifecycle,
        mcp_url=mcp_url,
    )


def _pin_keys_for(recipe: ToolRecipe, values: dict[str, str]) -> list[str]:
    declared = recipe.pin_keys
    if declared:
        return declared
    # Infer image pins from env.default (*_IMAGE).
    return sorted(k for k in values if k.endswith("_IMAGE"))


def _validate_pins(recipe: ToolRecipe) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    recipe_dir = recipe.recipe_dir
    env_default = recipe_dir / "env.default"
    if recipe.lifecycle == "external":
        # Escape hatch: no local images to pin.
        return diags
    if not env_default.is_file():
        if recipe.runtime.get("type") == "compose" or recipe.lifecycle == "managed":
            diags.append(
                error(
                    "env.default отсутствует в recipe",
                    code="1CX007",
                    source="tools",
                    suggestion="Добавьте pin образов в catalog/<id>/env.default",
                )
            )
        return diags
    values = _read_env_file(env_default)
    keys = _pin_keys_for(recipe, values)
    if not keys and recipe.lifecycle == "managed" and not recipe.is_scaffold:
        diags.append(
            warning(
                "в env.default нет *_IMAGE pin-ключей",
                code="1CX007",
                source="tools",
                suggestion="Объявите source.pins в tool.yaml или *_IMAGE в env.default",
            )
        )
    for key in keys:
        value = values.get(key, "")
        if not value or "REPLACE_ME" in value:
            severity = warning if recipe.is_scaffold else error
            diags.append(
                severity(
                    f"pin образа не задан: {key}",
                    code="1CX007",
                    source="tools",
                    suggestion=(
                        "Scaffold recipe — pin будет зафиксирован в Этапе 3"
                        if recipe.is_scaffold
                        else "Зафиксируйте tag или digest в env.default"
                    ),
                )
            )
    return diags


def _copy_recipe(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(
        src,
        dest,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git"),
    )
    env_default = dest / "env.default"
    user_env = dest / ".env"
    if env_default.is_file() and not user_env.is_file():
        shutil.copy2(env_default, user_env)


def _compose_pull(
    tool_dir: Path,
    recipe: ToolRecipe,
    *,
    progress: ProgressCb,
) -> tuple[bool, list[Diagnostic]]:
    compose = tool_dir / recipe.compose_file
    if not compose.is_file():
        return False, [
            error(
                f"compose file не найден: {recipe.compose_file}",
                code="1CX007",
                source="tools",
            )
        ]
    cmd = [
        "docker",
        "compose",
        "--project-directory",
        str(tool_dir),
        "-f",
        str(compose),
        "-p",
        recipe.project_name,
    ]
    user_env = tool_dir / ".env"
    env_file = user_env if user_env.is_file() else tool_dir / "env.default"
    if env_file.is_file():
        cmd.extend(["--env-file", str(env_file)])
    for profile in recipe.profiles:
        cmd.extend(["--profile", profile])
    cmd.append("pull")
    if progress:
        progress(f"docker compose pull ({recipe.id})…")
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(tool_dir),
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "COMPOSE_PROJECT_NAME": recipe.project_name},
        )
    except FileNotFoundError:
        return False, [
            error(
                "docker не найден в PATH",
                code="1CX003",
                source="tools",
                suggestion="Установите Docker / Docker Compose",
            )
        ]
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        msg = f"docker compose pull failed (exit {completed.returncode})"
        if detail:
            msg = f"{msg}: {detail[:500]}"
        return False, [
            error(
                msg,
                code="1CX006",
                source="tools",
                suggestion="Проверьте доступ к ghcr.io и pin образов в .env",
            )
        ]
    return True, [
        info("образы скачаны", code="1CX000", source="tools"),
    ]


def install_tool(
    tool_id: str,
    *,
    pull: bool = True,
    env: dict[str, str] | None = None,
    platform: str | None = None,
    progress: ProgressCb = None,
) -> InstallResult:
    """Materialize recipe into share; optionally pull images. Does not start service."""
    try:
        recipe = load_recipe(tool_id)
    except FileNotFoundError:
        available = ", ".join(list_catalog()) or "(пусто)"
        return InstallResult(
            tool_id=tool_id,
            status="error",
            diagnostics=[
                error(
                    f"tool «{tool_id}» не найден в catalog",
                    code="1CX001",
                    source="tools",
                    suggestion=f"Доступны: {available}",
                )
            ],
        )
    except (ValueError, OSError) as exc:
        return InstallResult(
            tool_id=tool_id,
            status="error",
            diagnostics=[
                error(str(exc), code="1CX007", source="tools"),
            ],
        )

    pin_diags = _validate_pins(recipe)
    if any(d.get("severity") == "error" for d in pin_diags):
        return InstallResult(tool_id=tool_id, status="error", diagnostics=pin_diags)

    dest = installed_tool_dir(tool_id, env=env, platform=platform)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if progress:
        progress(f"Копирую recipe → {dest}")
    try:
        _copy_recipe(recipe.recipe_dir, dest)
    except OSError as exc:
        return InstallResult(
            tool_id=tool_id,
            status="error",
            diagnostics=[
                error(
                    f"не удалось записать share: {exc}",
                    code="1CX006",
                    source="tools",
                )
            ],
        )

    diags: list[Diagnostic] = list(pin_diags)
    up_hint = (
        f"1c-dev services up {tool_id}"
        if recipe.lifecycle == "managed" and recipe.service_enabled
        else "1c-dev ide configure"
    )
    diags.append(
        info(
            f"recipe установлен в {dest}",
            code="1CX000",
            source="tools",
            suggestion=up_hint,
        )
    )
    pulled = False
    needs_pull = (
        pull
        and recipe.lifecycle == "managed"
        and recipe.runtime.get("type") == "compose"
        and not recipe.is_scaffold
    )
    if needs_pull:
        ok, pull_diags = _compose_pull(dest, recipe, progress=progress)
        diags.extend(pull_diags)
        if not ok:
            return InstallResult(
                tool_id=tool_id,
                status="error",
                path=str(dest),
                pulled=False,
                diagnostics=diags,
            )
        pulled = True
    elif pull and recipe.is_scaffold:
        diags.append(
            warning(
                "scaffold recipe: docker pull пропущен (pins/образы не готовы)",
                code="1CX007",
                source="tools",
            )
        )

    return InstallResult(
        tool_id=tool_id,
        status="ok",
        path=str(dest),
        pulled=pulled,
        diagnostics=diags,
    )


def remove_tool(
    tool_id: str,
    *,
    env: dict[str, str] | None = None,
    platform: str | None = None,
) -> RemoveResult:
    """Remove materialized recipe from share (does not docker compose down)."""
    dest = installed_tool_dir(tool_id, env=env, platform=platform)
    if not (dest / "tool.yaml").is_file():
        return RemoveResult(
            tool_id=tool_id,
            status="error",
            removed=False,
            diagnostics=[
                error(
                    f"tool «{tool_id}» не установлен",
                    code="1CX002",
                    source="tools",
                    suggestion=f"1c-dev tools install {tool_id}",
                )
            ],
        )
    try:
        shutil.rmtree(dest)
    except OSError as exc:
        return RemoveResult(
            tool_id=tool_id,
            status="error",
            removed=False,
            diagnostics=[
                error(f"не удалось удалить {dest}: {exc}", code="1CX006", source="tools"),
            ],
        )
    return RemoveResult(
        tool_id=tool_id,
        status="ok",
        removed=True,
        diagnostics=[
            warning(
                "recipe удалён из share; stack мог остаться запущенным",
                code="1CX000",
                source="tools",
                suggestion=f"1c-dev services down {tool_id}",
            )
        ],
    )
