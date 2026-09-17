"""Run environment doctor (ADR-005)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from adapters.platform.discovery import DiscoveryResult, discover_environment
from core.diagnostics import Diagnostic, error, warning
from core.doctor.capabilities import resolve_capabilities
from core.doctor.result import DoctorResult

_PLATFORM_HINT = (
    "Установите платформу 1С 8.3.x в стандартный каталог "
    "(/opt/1cv8/x86_64 на Linux или Program Files\\1cv8 на Windows)."
)
_IBCMD_HINT = (
    "Установите платформу 1С и добавьте ibcmd в PATH "
    "(или используйте стандартный каталог установки)."
)
_ONECV8_HINT = "Опционально для M1: добавьте 1cv8 в PATH, если нужен конфигуратор/толстый клиент."


def _tool_payload(found: bool, path: Path | None) -> dict[str, Any]:
    return {"found": found, "path": str(path) if path is not None else None}


def _platform_payload(discovery: DiscoveryResult) -> dict[str, Any]:
    p = discovery.platform
    return {
        "found": p.found,
        "version": p.version,
        "path": str(p.path) if p.path is not None else None,
    }


def run_doctor(*, search_roots: list[Path] | None = None) -> DoctorResult:
    """Discover environment and build doctor report."""
    discovery = discover_environment(search_roots=search_roots)

    tools = {
        "ibcmd": _tool_payload(discovery.ibcmd.found, discovery.ibcmd.path),
        "1cv8": _tool_payload(discovery.onecv8.found, discovery.onecv8.path),
    }
    tools_found = {
        "ibcmd": discovery.ibcmd.found,
        "1cv8": discovery.onecv8.found,
    }
    capabilities, gaps = resolve_capabilities(tools_found)

    diagnostics: list[Diagnostic] = []
    if not discovery.platform.found:
        diagnostics.append(
            error(
                "Платформа 1С не найдена",
                code="1CD001",
                source="doctor",
                suggestion=_PLATFORM_HINT,
            )
        )
    if not discovery.ibcmd.found:
        diagnostics.append(
            error(
                "ibcmd не найден",
                code="1CD002",
                source="doctor",
                suggestion=_IBCMD_HINT,
            )
        )
    if not discovery.onecv8.found:
        diagnostics.append(
            warning(
                "1cv8 не найден",
                code="1CD003",
                source="doctor",
                suggestion=_ONECV8_HINT,
            )
        )

    ok = discovery.platform.found and discovery.ibcmd.found
    return DoctorResult(
        status="ok" if ok else "error",
        platform=_platform_payload(discovery),
        tools=tools,
        capabilities=capabilities,
        gaps=gaps,
        diagnostics=diagnostics,
    )
