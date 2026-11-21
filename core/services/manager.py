"""Service lifecycle for installed external tools (ADR-033 Этап 2)."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from core.diagnostics import Diagnostic, error, info, warning
from core.services.compose import docker_available, port_in_use, run_compose
from core.services.health import check_http
from core.services.state import StackState, default_stack_labels, save_stack
from core.tools.catalog import list_catalog, load_recipe
from core.tools.install import (
    expand_template,
    is_installed,
    list_installed,
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


@dataclass
class ServiceListItem:
    """Catalog/state snapshot for services list (no live HTTP)."""

    tool_id: str
    name: str
    installed: bool
    running: bool | None = None
    healthy: bool | None = None
    mcp_url: str | None = None
    lifecycle: str = "managed"

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.tool_id,
            "name": self.name,
            "installed": self.installed,
            "running": self.running,
            "healthy": self.healthy,
            "mcpUrl": self.mcp_url,
            "lifecycle": self.lifecycle,
        }


@dataclass
class BulkServiceResult:
    """Aggregated result of services * --all."""

    status: Status
    action: str
    results: list[ServiceResult] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "action": self.action,
            "results": [r.to_payload() for r in self.results],
        }


def _aggregate_service_status(results: list[ServiceResult]) -> Status:
    if any(r.status == "error" for r in results):
        return "error"
    if any(r.status == "degraded" for r in results):
        return "degraded"
    return "ok"


def _is_managed_recipe(recipe: Any) -> bool:
    return recipe.lifecycle == "managed" and bool(recipe.service_enabled)


def _managed_catalog_ids() -> list[str]:
    ids: list[str] = []
    for tool_id in list_catalog():
        try:
            recipe = load_recipe(tool_id)
        except (FileNotFoundError, ValueError, OSError):
            continue
        if _is_managed_recipe(recipe):
            ids.append(tool_id)
    return ids


def _skip_not_installed(tool_id: str, action: str) -> ServiceResult:
    return ServiceResult(
        tool_id=tool_id,
        status="ok",
        action=action,
        diagnostics=[
            warning(
                f"tool «{tool_id}» не установлен — пропуск",
                code="1CX002",
                source="services",
                suggestion=f"1c-dev tools install {tool_id}",
            )
        ],
    )


def _mcp_url_for_list(
    recipe: Any,
    *,
    installed: bool,
    stack: Any | None,
) -> str | None:
    if installed:
        try:
            env_vars = resolve_env_vars(installed_tool_dir(recipe.id))
            if recipe.mcp_url_template:
                return expand_template(recipe.mcp_url_template, env_vars)
        except OSError:
            return stack.mcp_url if stack else None
    if stack and stack.mcp_url:
        return str(stack.mcp_url)
    return None


def list_services() -> list[ServiceListItem]:
    """List managed services from catalog ∪ orphan installed (state, no live HTTP)."""
    from core.services.state import load_state

    state = load_state()
    items: list[ServiceListItem] = []
    seen: set[str] = set()

    for tool_id in _managed_catalog_ids():
        seen.add(tool_id)
        recipe = load_recipe(tool_id)
        installed = is_installed(tool_id)
        stack = state.get(tool_id)
        items.append(
            ServiceListItem(
                tool_id=tool_id,
                name=recipe.name,
                installed=installed,
                running=stack.running if stack else None,
                healthy=stack.healthy if stack else None,
                mcp_url=_mcp_url_for_list(recipe, installed=installed, stack=stack),
                lifecycle=recipe.lifecycle,
            )
        )

    for tool_id in list_installed():
        if tool_id in seen:
            continue
        try:
            recipe = load_installed_recipe(tool_id)
        except (FileNotFoundError, ValueError, OSError):
            continue
        if not _is_managed_recipe(recipe):
            continue
        stack = state.get(tool_id)
        items.append(
            ServiceListItem(
                tool_id=tool_id,
                name=recipe.name,
                installed=True,
                running=stack.running if stack else None,
                healthy=stack.healthy if stack else None,
                mcp_url=_mcp_url_for_list(recipe, installed=True, stack=stack),
                lifecycle=recipe.lifecycle,
            )
        )
    return items


def _services_all(
    action: str,
    *,
    progress: ProgressCb = None,
    wait_health_sec: float = 120.0,
) -> BulkServiceResult:
    """Run up/down/status for all catalog managed tools (skip not-installed)."""
    results: list[ServiceResult] = []
    for tool_id in _managed_catalog_ids():
        if not is_installed(tool_id):
            results.append(_skip_not_installed(tool_id, action))
            continue
        if progress:
            progress(f"services {action} {tool_id}…")
        if action == "up":
            results.append(
                service_up(
                    tool_id, progress=progress, wait_health_sec=wait_health_sec
                )
            )
        elif action == "down":
            results.append(service_down(tool_id, progress=progress))
        else:
            results.append(service_status(tool_id))
    return BulkServiceResult(
        status=_aggregate_service_status(results),
        action=f"{action}-all",
        results=results,
    )


def service_up_all(
    *,
    progress: ProgressCb = None,
    wait_health_sec: float = 120.0,
) -> BulkServiceResult:
    return _services_all(
        "up", progress=progress, wait_health_sec=wait_health_sec
    )


def service_down_all(*, progress: ProgressCb = None) -> BulkServiceResult:
    return _services_all("down", progress=progress)


def service_status_all() -> BulkServiceResult:
    return _services_all("status")


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


def _runtime_type(recipe: Any) -> str:
    return str(recipe.runtime.get("type") or "compose")


def _require_managed(tool_id: str, action: str) -> ServiceResult | None:
    if not is_installed(tool_id):
        return _not_installed(tool_id, action)
    recipe = load_installed_recipe(tool_id)
    if recipe.lifecycle != "managed" or not recipe.service_enabled:
        return _not_managed(tool_id, action, recipe.lifecycle)
    runtime_type = _runtime_type(recipe)
    if runtime_type not in ("compose", "process"):
        return ServiceResult(
            tool_id=tool_id,
            status="error",
            action=action,
            diagnostics=[
                error(
                    f"runtime.type={runtime_type} не поддерживается "
                    "(compose|process)",
                    code="1CX007",
                    source="services",
                )
            ],
        )
    return None


def _wait_health(
    health_url: str,
    *,
    wait_health_sec: float,
    progress: ProgressCb,
) -> bool:
    if wait_health_sec <= 0:
        return check_http(health_url, timeout_sec=2.0).reachable
    if progress:
        progress(f"Ожидаю health {health_url}…")
    deadline = time.monotonic() + wait_health_sec
    while time.monotonic() < deadline:
        if check_http(health_url, timeout_sec=2.0).reachable:
            return True
        time.sleep(1.0)
    return False


def _check_port_conflict(
    tool_id: str,
    recipe: Any,
    health_url: str | None,
    mcp_url: str | None,
    tool_dir: Path,
    diags: list[Diagnostic],
) -> ServiceResult | None:
    """Return ok result if already healthy; error if port busy; else None."""
    if not health_url:
        return None
    port = _port_from_url(health_url)
    if port is None or not port_in_use("127.0.0.1", port):
        return None
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
                f"Освободите 127.0.0.1:{port} или смените порт в {tool_dir / '.env'}"
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


def _service_up_compose(
    tool_id: str,
    *,
    progress: ProgressCb = None,
    wait_health_sec: float = 120.0,
) -> ServiceResult:
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

    conflict = _check_port_conflict(
        tool_id, recipe, health_url, mcp_url, tool_dir, diags
    )
    if conflict is not None:
        return conflict

    up_args = ["up", "-d", "--remove-orphans"]
    if recipe.compose_build:
        up_args.insert(1, "--build")
    compose_result = run_compose(
        tool_dir,
        recipe,
        up_args,
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
        healthy = _wait_health(
            health_url, wait_health_sec=wait_health_sec, progress=progress
        )
        if not healthy:
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

    if recipe.index_config.get("load_on") == "services_up":
        from core.tools.bsl_search_index import ensure_index_loaded

        ok_idx, idx_diags = ensure_index_loaded(recipe, tool_dir, progress=progress)
        diags.extend(idx_diags)
        if not ok_idx:
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


def _service_up_process(
    tool_id: str,
    *,
    progress: ProgressCb = None,
    wait_health_sec: float = 60.0,
) -> ServiceResult:
    from core.services.process import alive_pid, start_process

    recipe = load_installed_recipe(tool_id)
    tool_dir = installed_tool_dir(tool_id)
    health_url, mcp_url, _env = _urls_for(tool_id)
    diags: list[Diagnostic] = []

    # Idempotent: our pid already alive + healthy.
    pid = alive_pid(tool_id)
    if pid is not None and health_url and check_http(health_url, timeout_sec=2.0).reachable:
        out = ServiceResult(
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
                    f"process уже healthy (pid={pid})",
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
        return out

    conflict = _check_port_conflict(
        tool_id, recipe, health_url, mcp_url, tool_dir, diags
    )
    if conflict is not None:
        return conflict

    ok, start_diags = start_process(tool_id, recipe, progress=progress)
    diags.extend(start_diags)
    if not ok:
        return ServiceResult(
            tool_id=tool_id,
            status="error",
            action="up",
            health_url=health_url,
            mcp_url=mcp_url,
            project_name=recipe.project_name,
            diagnostics=diags,
        )

    healthy = True
    if health_url:
        healthy = _wait_health(
            health_url, wait_health_sec=wait_health_sec, progress=progress
        )
        if not healthy:
            diags.append(
                error(
                    f"health unreachable: {health_url}",
                    code="1CX005",
                    source="services",
                    suggestion=f"1c-dev services logs {tool_id}",
                )
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
            return ServiceResult(
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
        healthy=healthy,
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
        healthy=True,
        running=True,
        health_url=health_url,
        mcp_url=mcp_url,
    )
    return out


def service_up(
    tool_id: str,
    *,
    progress: ProgressCb = None,
    wait_health_sec: float = 120.0,
) -> ServiceResult:
    blocked = _require_managed(tool_id, "up")
    if blocked is not None:
        return blocked
    recipe = load_installed_recipe(tool_id)
    if _runtime_type(recipe) == "process":
        return _service_up_process(
            tool_id, progress=progress, wait_health_sec=min(wait_health_sec, 90.0)
        )
    return _service_up_compose(
        tool_id, progress=progress, wait_health_sec=wait_health_sec
    )


def service_down(tool_id: str, *, progress: ProgressCb = None) -> ServiceResult:
    blocked = _require_managed(tool_id, "down")
    if blocked is not None:
        return blocked
    recipe = load_installed_recipe(tool_id)
    tool_dir = installed_tool_dir(tool_id)
    if _runtime_type(recipe) == "process":
        from core.services.process import stop_process

        ok, diags = stop_process(tool_id, progress=progress)
        out = ServiceResult(
            tool_id=tool_id,
            status="ok" if ok else "error",
            action="down",
            running=False if ok else None,
            healthy=False,
            project_name=recipe.project_name,
            diagnostics=diags
            or [info("сервис остановлен", code="1CX000", source="services")],
        )
    else:
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
        status=out.status,
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
    runtime = _runtime_type(recipe)
    if (
        recipe.lifecycle == "managed"
        and recipe.service_enabled
        and runtime == "compose"
        and not docker_available()
    ):
        diags.append(
            warning(
                "docker не найден — статус только по health HTTP",
                code="1CX003",
                source="services",
            )
        )
    running: bool | None = None
    if runtime == "process" and recipe.lifecycle == "managed":
        from core.services.process import alive_pid

        running = alive_pid(tool_id) is not None
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
    if running is None:
        running = healthy
    status: Status = "ok" if healthy else "degraded"
    out = ServiceResult(
        tool_id=tool_id,
        status=status,
        action="status",
        running=running,
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
            running=running,
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
    if _runtime_type(recipe) == "process":
        from core.services.process import read_process_logs

        return ServiceResult(
            tool_id=tool_id,
            status="ok",
            action="logs",
            project_name=recipe.project_name,
            logs=read_process_logs(tool_id, tail=tail),
            diagnostics=[],
        )
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
