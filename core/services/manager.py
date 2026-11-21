"""Service lifecycle for installed external tools (Этап 1: v8std compose)."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from core.diagnostics import Diagnostic, error, info, warning
from core.services.compose import docker_available, port_in_use, run_compose
from core.services.health import check_http
from core.tools.install import (
    expand_template,
    is_installed,
    load_installed_recipe,
    resolve_env_vars,
)
from core.tools.paths import installed_tool_dir

ProgressCb = Callable[[str], None] | None
Status = Literal["ok", "error", "degraded"]


@dataclass
class ServiceResult:
    tool_id: str
    status: Status
    action: str
    running: bool | None = None
    healthy: bool | None = None
    health_url: str | None = None
    mcp_url: str | None = None
    logs: str | None = None
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "toolId": self.tool_id,
            "status": self.status,
            "action": self.action,
            "running": self.running,
            "healthy": self.healthy,
            "healthUrl": self.health_url,
            "mcpUrl": self.mcp_url,
            "diagnostics": list(self.diagnostics),
        }
        if self.logs is not None:
            payload["logs"] = self.logs
        return payload


def _not_installed(tool_id: str, action: str) -> ServiceResult:
    return ServiceResult(
        tool_id=tool_id,
        status="error",
        action=action,
        diagnostics=[
            error(
                f"tool «{tool_id}» не установлен",
                code="1CX002",
                source="services",
                suggestion=f"1c-dev tools install {tool_id}",
            )
        ],
    )


def _urls_for(tool_id: str) -> tuple[str | None, str | None, dict[str, str]]:
    recipe = load_installed_recipe(tool_id)
    tool_dir = recipe.recipe_dir
    env_vars = resolve_env_vars(tool_dir)
    health = (
        expand_template(recipe.health_url_template, env_vars)
        if recipe.health_url_template
        else None
    )
    mcp = (
        expand_template(recipe.mcp_url_template, env_vars)
        if recipe.mcp_url_template
        else None
    )
    return health, mcp, env_vars


def _port_from_url(url: str) -> int | None:
    match = re.search(r":(\d+)(?:/|$)", url)
    if not match:
        return None
    return int(match.group(1))


def service_up(
    tool_id: str,
    *,
    progress: ProgressCb = None,
    wait_health_sec: float = 120.0,
) -> ServiceResult:
    if not is_installed(tool_id):
        return _not_installed(tool_id, "up")
    if not docker_available():
        return ServiceResult(
            tool_id=tool_id,
            status="error",
            action="up",
            diagnostics=[
                error(
                    "docker не найден в PATH",
                    code="1CX003",
                    source="services",
                    suggestion="Установите Docker / Docker Compose",
                )
            ],
        )

    recipe = load_installed_recipe(tool_id)
    tool_dir = installed_tool_dir(tool_id)
    health_url, mcp_url, _env = _urls_for(tool_id)
    diags: list[Diagnostic] = []

    if health_url:
        port = _port_from_url(health_url)
        if port is not None and port_in_use("127.0.0.1", port):
            # Already listening — check health; may be our stack (idempotent).
            probe = check_http(health_url, timeout_sec=2.0)
            if probe.reachable:
                return ServiceResult(
                    tool_id=tool_id,
                    status="ok",
                    action="up",
                    running=True,
                    healthy=True,
                    health_url=health_url,
                    mcp_url=mcp_url,
                    diagnostics=[
                        info(
                            f"сервис уже healthy на {health_url}",
                            code="1CX000",
                            source="services",
                        )
                    ],
                )
            diags.append(
                error(
                    f"порт {port} занят, health unreachable",
                    code="1CX004",
                    source="services",
                    suggestion=(
                        f"Освободите 127.0.0.1:{port} или смените порт в "
                        f"{tool_dir / '.env'}"
                    ),
                )
            )
            return ServiceResult(
                tool_id=tool_id,
                status="error",
                action="up",
                running=None,
                healthy=False,
                health_url=health_url,
                mcp_url=mcp_url,
                diagnostics=diags,
            )

    result = run_compose(
        tool_dir,
        recipe,
        ["up", "-d", "--remove-orphans"],
        progress=progress,
    )
    diags.extend(result.diagnostics)
    if not result.ok:
        return ServiceResult(
            tool_id=tool_id,
            status="error",
            action="up",
            health_url=health_url,
            mcp_url=mcp_url,
            diagnostics=diags,
        )

    healthy = None
    if health_url and wait_health_sec > 0:
        if progress:
            progress(f"Ожидаю health {health_url}…")
        deadline = time.monotonic() + wait_health_sec
        while time.monotonic() < deadline:
            probe = check_http(health_url, timeout_sec=2.0)
            if probe.reachable:
                healthy = True
                break
            time.sleep(2.0)
        if healthy is not True:
            healthy = False
            diags.append(
                error(
                    f"health unreachable: {health_url}",
                    code="1CX005",
                    source="services",
                    suggestion=f"1c-dev services logs {tool_id}",
                )
            )
            return ServiceResult(
                tool_id=tool_id,
                status="error",
                action="up",
                running=True,
                healthy=False,
                health_url=health_url,
                mcp_url=mcp_url,
                diagnostics=diags,
            )

    diags.append(
        info(
            "сервис поднят",
            code="1CX000",
            source="services",
            suggestion="1c-dev ide configure",
        )
    )
    return ServiceResult(
        tool_id=tool_id,
        status="ok",
        action="up",
        running=True,
        healthy=healthy if healthy is not None else True,
        health_url=health_url,
        mcp_url=mcp_url,
        diagnostics=diags,
    )


def service_down(tool_id: str, *, progress: ProgressCb = None) -> ServiceResult:
    if not is_installed(tool_id):
        return _not_installed(tool_id, "down")
    recipe = load_installed_recipe(tool_id)
    tool_dir = installed_tool_dir(tool_id)
    result = run_compose(tool_dir, recipe, ["down"], progress=progress)
    if not result.ok:
        return ServiceResult(
            tool_id=tool_id,
            status="error",
            action="down",
            diagnostics=result.diagnostics,
        )
    return ServiceResult(
        tool_id=tool_id,
        status="ok",
        action="down",
        running=False,
        healthy=False,
        diagnostics=[
            info("сервис остановлен", code="1CX000", source="services"),
        ],
    )


def service_status(tool_id: str) -> ServiceResult:
    if not is_installed(tool_id):
        return _not_installed(tool_id, "status")
    health_url, mcp_url, _ = _urls_for(tool_id)
    diags: list[Diagnostic] = []
    if not docker_available():
        diags.append(
            warning(
                "docker не найден — статус только по health HTTP",
                code="1CX003",
                source="services",
            )
        )
    healthy = False
    if health_url:
        probe = check_http(health_url, timeout_sec=2.0)
        healthy = probe.reachable
        if not healthy:
            diags.append(
                warning(
                    f"health unreachable: {health_url}",
                    code="1CX005",
                    source="services",
                    suggestion=f"1c-dev services up {tool_id}",
                )
            )
    status: Status = "ok" if healthy else "degraded"
    return ServiceResult(
        tool_id=tool_id,
        status=status,
        action="status",
        running=healthy,
        healthy=healthy,
        health_url=health_url,
        mcp_url=mcp_url,
        diagnostics=diags,
    )


def service_logs(
    tool_id: str,
    *,
    tail: int = 100,
    progress: ProgressCb = None,
) -> ServiceResult:
    if not is_installed(tool_id):
        return _not_installed(tool_id, "logs")
    recipe = load_installed_recipe(tool_id)
    tool_dir = installed_tool_dir(tool_id)
    result = run_compose(
        tool_dir,
        recipe,
        ["logs", "--no-color", "--tail", str(tail)],
        progress=progress,
    )
    if not result.ok:
        return ServiceResult(
            tool_id=tool_id,
            status="error",
            action="logs",
            diagnostics=result.diagnostics,
        )
    return ServiceResult(
        tool_id=tool_id,
        status="ok",
        action="logs",
        logs=(result.stdout or "") + (result.stderr or ""),
        diagnostics=[],
    )
