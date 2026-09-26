"""Run environment doctor (ADR-005, ADR-007, ADR-012, ADR-013 / #49)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from adapters.platform.discovery import DiscoveryResult, discover_environment
from adapters.source.mdclasses.resolve import resolve_jar as resolve_mdreader_jar
from adapters.source.xmlgen.resolve import resolve_jar as resolve_xmlgen_jar
from adapters.source.xmlgen.resolve import resolve_java
from core.diagnostics import Diagnostic, error, info, warning
from core.doctor.capabilities import resolve_capabilities
from core.doctor.result import DoctorResult
from core.toolchain.manifest import load_manifest
from core.toolchain.resolve import JarResolve, resolve_component_jar, sync_suggestion

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
    "Установите JDK 17+ (xml-gen) / JDK 21+ (md-reader, BSL LS) "
    "и добавьте java в PATH (или задайте JAVA_HOME)."
)
_JAVA21_HINT = (
    "Для md-reader и BSL Language Server нужен JDK 21+ "
    "(JAVA_HOME / java в PATH)."
)
_CLI_HINT = (
    "Установите CLI: uv tool install git+https://github.com/pila86/1c-dev "
    "(или poetry install для разработки)."
)
_XMLGEN_ENV = "ONEC_XMLGEN_JAR"
_MDREADER_ENV = "ONEC_MDREADER_JAR"


def _tool_payload(
    found: bool,
    path: Path | None,
    *,
    version: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "found": found,
        "path": str(path) if path is not None else None,
    }
    if version is not None:
        payload["version"] = version
    if source is not None:
        payload["source"] = source
    return payload


def _jar_payload(resolved: JarResolve) -> dict[str, Any]:
    return _tool_payload(
        resolved.found,
        resolved.path,
        source=resolved.source,
    )


def _adapter_jar_payload(
    found: bool,
    path: Path | None,
    *,
    env_name: str,
    env: dict[str, str] | None,
) -> dict[str, Any]:
    """Build tool payload for xml-gen / md-reader with env|cache source."""
    environ = env if env is not None else os.environ
    source: str | None = None
    if found and path is not None:
        override = environ.get(env_name, "").strip()
        if override:
            source = "env"
        else:
            source = "cache"
    elif environ.get(env_name, "").strip():
        source = "env"
    return _tool_payload(found, path, source=source)


def _platform_payload(discovery: DiscoveryResult) -> dict[str, Any]:
    p = discovery.platform
    return {
        "found": p.found,
        "version": p.version,
        "path": str(p.path) if p.path is not None else None,
    }


def _resolve_cli() -> dict[str, Any]:
    which = shutil.which("1c-dev")
    if which:
        return _tool_payload(True, Path(which))
    return _tool_payload(False, None)


def run_doctor(
    *,
    search_roots: list[Path] | None = None,
    env: dict[str, str] | None = None,
) -> DoctorResult:
    """Discover environment and build doctor report."""
    discovery = discover_environment(search_roots=search_roots)
    java = resolve_java(env=env)
    xmlgen = resolve_xmlgen_jar(env=env)
    mdreader = resolve_mdreader_jar(env=env)
    cli = _resolve_cli()

    manifest = load_manifest()
    bsl_spec = manifest.get("bsl-language-server")
    docs_spec = manifest.get("docs-facade")
    bsl = (
        resolve_component_jar(bsl_spec, env=env)
        if bsl_spec is not None
        else JarResolve(found=False)
    )
    docs = (
        resolve_component_jar(docs_spec, env=env)
        if docs_spec is not None
        else JarResolve(found=False, deferred=True)
    )

    tools = {
        "cli": cli,
        "ibcmd": _tool_payload(discovery.ibcmd.found, discovery.ibcmd.path),
        "1cv8": _tool_payload(discovery.onecv8.found, discovery.onecv8.path),
        "java": _tool_payload(java.found, java.path, version=java.version),
        "xml-gen": _adapter_jar_payload(
            xmlgen.found, xmlgen.path, env_name=_XMLGEN_ENV, env=env
        ),
        "md-reader": _adapter_jar_payload(
            mdreader.found, mdreader.path, env_name=_MDREADER_ENV, env=env
        ),
        "bsl-language-server": _jar_payload(bsl),
        "docs-facade": _jar_payload(docs),
    }
    tools_found = {
        "ibcmd": discovery.ibcmd.found,
        "1cv8": discovery.onecv8.found,
        "java": java.found,
        "xml-gen": xmlgen.found,
        "md-reader": mdreader.found,
        "bsl-language-server": bsl.found,
        "docs-facade": docs.found,
        "cli": bool(cli.get("found")),
    }
    capabilities, gaps = resolve_capabilities(tools_found)

    hint = sync_suggestion()
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
                "Java 17+ не найдена (metadata.create); для metadata.read / BSL LS нужен JDK 21+",
                code="1CD004",
                source="doctor",
                suggestion=_JAVA_HINT,
            )
        )
    elif java.version is not None:
        try:
            major = int(java.version)
        except ValueError:
            major = 0
        if major < 21:
            diagnostics.append(
                warning(
                    f"Java {major} найдена; для md-reader и BSL Language Server нужен JDK 21+",
                    code="1CD010",
                    source="doctor",
                    suggestion=_JAVA21_HINT,
                )
            )
    if not xmlgen.found:
        diagnostics.append(
            warning(
                "xml-gen jar не найден (нужен для metadata.create)",
                code="1CD005",
                source="doctor",
                suggestion=f"{hint} (или задайте {_XMLGEN_ENV}).",
            )
        )
    if not mdreader.found:
        diagnostics.append(
            warning(
                "md-reader jar не найден (нужен для metadata.list/get/find)",
                code="1CD006",
                source="doctor",
                suggestion=f"{hint} (или задайте {_MDREADER_ENV}).",
            )
        )
    if not bsl.found:
        env_name = (bsl_spec.env if bsl_spec else None) or "ONEC_BSLLS_JAR"
        diagnostics.append(
            warning(
                "bsl-language-server jar не найден (нужен для BSL LS MCP)",
                code="1CD007",
                source="doctor",
                suggestion=f"{hint} (или задайте {env_name}).",
            )
        )
    if docs.deferred and not docs.found:
        diagnostics.append(
            info(
                "docs-facade отложен (ожидает реализации #51)",
                code="1CD008",
                source="doctor",
                suggestion=(
                    "Компонент появится после #51; "
                    "env ONEC_DOCS_FACADE_JAR уже поддерживается."
                ),
            )
        )
    elif not docs.found:
        env_name = (docs_spec.env if docs_spec else None) or "ONEC_DOCS_FACADE_JAR"
        diagnostics.append(
            warning(
                "docs-facade jar не найден",
                code="1CD008",
                source="doctor",
                suggestion=f"{hint} (или задайте {env_name}).",
            )
        )
    if not cli.get("found"):
        diagnostics.append(
            warning(
                "CLI 1c-dev не найден в PATH",
                code="1CD009",
                source="doctor",
                suggestion=_CLI_HINT,
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
