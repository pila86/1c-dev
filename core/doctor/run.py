"""Run environment doctor (ADR-005, ADR-007, ADR-012)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from adapters.platform.discovery import DiscoveryResult, discover_environment
from adapters.source.mdclasses.resolve import (
    fetch_script_suggestion as mdreader_suggest,
)
from adapters.source.mdclasses.resolve import resolve_jar as resolve_mdreader_jar
from adapters.source.xmlgen.resolve import (
    fetch_script_suggestion as xmlgen_suggest,
)
from adapters.source.xmlgen.resolve import resolve_jar as resolve_xmlgen_jar
from adapters.source.xmlgen.resolve import resolve_java
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
_ONECV8_HINT = (
    "Опционально для M1: добавьте 1cv8 в PATH, если нужен конфигуратор/толстый клиент."
)
_JAVA_HINT = (
    "Установите JDK 17+ (xml-gen) / JDK 21+ (md-reader) "
    "и добавьте java в PATH (или задайте JAVA_HOME)."
)


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
    java = resolve_java()
    xmlgen = resolve_xmlgen_jar()
    mdreader = resolve_mdreader_jar()

    tools = {
        "ibcmd": _tool_payload(discovery.ibcmd.found, discovery.ibcmd.path),
        "1cv8": _tool_payload(discovery.onecv8.found, discovery.onecv8.path),
        "java": _tool_payload(java.found, java.path),
        "xml-gen": _tool_payload(xmlgen.found, xmlgen.path),
        "md-reader": _tool_payload(mdreader.found, mdreader.path),
    }
    tools_found = {
        "ibcmd": discovery.ibcmd.found,
        "1cv8": discovery.onecv8.found,
        "java": java.found,
        "xml-gen": xmlgen.found,
        "md-reader": mdreader.found,
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
    if not java.found:
        diagnostics.append(
            warning(
                "Java 17+ не найдена (metadata.create); для metadata.read нужен JDK 21+",
                code="1CD004",
                source="doctor",
                suggestion=_JAVA_HINT,
            )
        )
    if not xmlgen.found:
        diagnostics.append(
            warning(
                "xml-gen jar не найден (нужен для metadata.create)",
                code="1CD005",
                source="doctor",
                suggestion=(
                    f"Соберите xml-gen: {xmlgen_suggest()} (или задайте ONEC_XMLGEN_JAR)."
                ),
            )
        )
    if not mdreader.found:
        diagnostics.append(
            warning(
                "md-reader jar не найден (нужен для metadata.list/get/find)",
                code="1CD006",
                source="doctor",
                suggestion=(
                    f"Соберите md-reader: {mdreader_suggest()} "
                    "(или задайте ONEC_MDREADER_JAR)."
                ),
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
