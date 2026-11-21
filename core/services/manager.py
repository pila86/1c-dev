"""Service lifecycle for installed external tools (ADR-033 Этап 2)."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from core.diagnostics import Diagnostic, error, info, warning
from core.services.compose import docker_available, port_in_use, run_compose
from core.services.health import check_http
from core.services.state import StackState, default_stack_labels, save_stack
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
    project_name: str | None = None
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
            "projectName": self.project_name,
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


def _not_managed(tool_id: str, action: str, lifecycle: str) -> ServiceResult:
    return ServiceResult(
        tool_id=tool_id,
        status="error",
        action=action,
        diagnostics=[
            error(
                f"tool «{tool_id}» lifecycle={lifecycle} — services не применимы",
                code="1CX007",
                source="services",
                suggestion="Для external URL используйте ide configure",
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


def _persist(
    tool_id: str,
    *,
    project_name: str,
    action: str,
    status: Status,
    healthy: bool | None,
    running: bool | None,
    health_url: str | None,
    mcp_url: str | None,
) -> None:
    save_stack(
        StackState(
            tool_id=tool_id,
            project_name=project_name,
            last_action=action,
            last_status=status,
            healthy=healthy,
            running=running,
            health_url=health_url,
            mcp_url=mcp_url,
            updated_at=datetime.now(UTC).isoformat(),
            labels=default_stack_labels(tool_id),
        )
    )


def _require_managed(tool_id: str, action: str) -> ServiceResult | None:
    if not is_installed(tool_id):
        return _not_installed(tool_id, action)
    recipe = load_installed_recipe(tool_id)
    if recipe.lifecycle != "managed" or not recipe.service_enabled:
        return _not_managed(tool_id, action, recipe.lifecycle)
    # Этап 2: только compose adapter; пустой type трактуем как compose.
    runtime_type = str(recipe.runtime.get("type") or "compose")
    if runtime_type != "compose":
        return ServiceResult(
            tool_id=tool_id,
            status="error",
            action=action,
            diagnostics=[
                error(
                    f"runtime.type={runtime_type} не поддерживается (только compose)",
                    code="1CX007",
                    source="services",
                )
            ],
        )
    return None


def service_up(
    tool_id: str,
    *,
    progress: ProgressCb = None,
    wait_health_sec: float = 120.0,
) -> ServiceResult:
    blocked = _require_managed(tool_id, "up")
    if blocked is not None:
        return blocked
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
                result = ServiceResult(
                    tool_id=tool_id,
                    status="ok",
                    action="up",
                    running=True,
                    healthy=True,
                    health_url=health_url,
                    mcp_url=mcp_url,
                    project_name=recipe.project_name,
                    diagnostics=[
                        info(
                            f"сервис уже healthy на {health_url}",
                            code="1CX000",
                            source="services",
                        )
                    ],
                )
                _persist(
                    tool_id,
                    project_name=recipe.project_name,
                    action="up",
                    status="ok",
                    healthy=True,
                    running=True,
                    health_url=health_url,
                    mcp_url=mcp_url,
                )
                return result
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
                project_name=recipe.project_name,
                diagnostics=diags,
            )

    compose_result = run_compose(
        tool_dir,
        recipe,
        ["up", "-d", "--remove-orphans"],
        progress=progress,
    )
    diags.extend(compose_result.diagnostics)
    if not compose_result.ok:
        return ServiceResult(
            tool_id=tool_id,
            status="error",
            action="up",
            health_url=health_url,
            mcp_url=mcp_url,
            project_name=recipe.project_name,
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
            out = ServiceResult(
                tool_id=tool_id,
                status="error",
                action="up",
                running=True,
                healthy=False,
                health_url=health_url,
                mcp_url=mcp_url,
                project_name=recipe.project_name,
                diagnostics=diags,
            )
            _persist(
                tool_id,
                project_name=recipe.project_name,
                action="up",
                status="error",
                healthy=False,
                running=True,
                health_url=health_url,
                mcp_url=mcp_url,
            )
            return out

    diags.append(
        info(
            "сервис поднят",
            code="1CX000",
            source="services",
            suggestion="1c-dev ide configure",
        )
    )
    out = ServiceResult(
        tool_id=tool_id,
        status="ok",
        action="up",
        running=True,
        healthy=healthy if healthy is not None else True,
        health_url=health_url,
        mcp_url=mcp_url,
        project_name=recipe.project_name,
        diagnostics=diags,
    )
    _persist(
        tool_id,
        project_name=recipe.project_name,
        action="up",
        status="ok",
        healthy=out.healthy,
        running=True,
        health_url=health_url,
        mcp_url=mcp_url,
    )
    return out


def service_down(tool_id: str, *, progress: ProgressCb = None) -> ServiceResult:
    blocked = _require_managed(tool_id, "down")
    if blocked is not None:
        return blocked
    recipe = load_installed_recipe(tool_id)
    tool_dir = installed_tool_dir(tool_id)
    result = run_compose(tool_dir, recipe, ["down"], progress=progress)
    if not result.ok:
        return ServiceResult(
            tool_id=tool_id,
            status="error",
            action="down",
            project_name=recipe.project_name,
            diagnostics=result.diagnostics,
        )
    out = ServiceResult(
        tool_id=tool_id,
        status="ok",
        action="down",
        running=False,
        healthy=False,
        project_name=recipe.project_name,
        diagnostics=[
            info("сервис остановлен", code="1CX000", source="services"),
        ],
    )
    health_url, mcp_url, _ = _urls_for(tool_id)
    _persist(
        tool_id,
        project_name=recipe.project_name,
        action="down",
        status="ok",
        healthy=False,
        running=False,
        health_url=health_url,
        mcp_url=mcp_url,
    )
    return out


def service_restart(
    tool_id: str,
    *,
    progress: ProgressCb = None,
    wait_health_sec: float = 120.0,
) -> ServiceResult:
    """Restart managed stack: down then up (idempotent via up)."""
    blocked = _require_managed(tool_id, "restart")
    if blocked is not None:
        return blocked
    down = service_down(tool_id, progress=progress)
    if down.status != "ok":
        down.action = "restart"
        return down
    up = service_up(tool_id, progress=progress, wait_health_sec=wait_health_sec)
    up.action = "restart"
    return up


def service_status(tool_id: str) -> ServiceResult:
    if not is_installed(tool_id):
        return _not_installed(tool_id, "status")
    recipe = load_installed_recipe(tool_id)
    health_url, mcp_url, _ = _urls_for(tool_id)
    diags: list[Diagnostic] = []
    if recipe.lifecycle == "managed" and recipe.service_enabled and not docker_available():
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
            suggestion = (
                f"1c-dev services up {tool_id}"
                if recipe.lifecycle == "managed"
                else "Проверьте external endpoint"
            )
            diags.append(
                warning(
                    f"health unreachable: {health_url}",
                    code="1CX005",
                    source="services",
                    suggestion=suggestion,
                )
            )
    status: Status = "ok" if healthy else "degraded"
    out = ServiceResult(
        tool_id=tool_id,
        status=status,
        action="status",
        running=healthy,
        healthy=healthy,
        health_url=health_url,
        mcp_url=mcp_url,
        project_name=recipe.project_name,
        diagnostics=diags,
    )
    if recipe.lifecycle == "managed" and recipe.service_enabled:
        _persist(
            tool_id,
            project_name=recipe.project_name,
            action="status",
            status=status,
            healthy=healthy,
            running=healthy,
            health_url=health_url,
            mcp_url=mcp_url,
        )
    return out


def service_logs(
    tool_id: str,
    *,
    tail: int = 100,
    progress: ProgressCb = None,
) -> ServiceResult:
    blocked = _require_managed(tool_id, "logs")
    if blocked is not None:
        return blocked
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
            project_name=recipe.project_name,
            diagnostics=result.diagnostics,
        )
    return ServiceResult(
        tool_id=tool_id,
        status="ok",
        action="logs",
        project_name=recipe.project_name,
        logs=(result.stdout or "") + (result.stderr or ""),
        diagnostics=[],
    )
