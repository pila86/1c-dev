"""Idempotent toolchain sync (`1c-dev tools sync`)."""

from __future__ import annotations

from pathlib import Path

from core.diagnostics import Diagnostic, info
from core.toolchain.cache import tools_cache_dir
from core.toolchain.fetchers.bslls import fetch_bsl_language_server
from core.toolchain.fetchers.mdreader import fetch_md_reader
from core.toolchain.fetchers.xmlgen import fetch_xml_gen
from core.toolchain.manifest import ComponentSpec, ToolchainManifest, load_manifest
from core.toolchain.result import ComponentResult, OverallStatus, SyncResult

MUST_IDS = frozenset({"xml-gen", "md-reader"})
SOFT_IDS = frozenset({"bsl-language-server"})


def _sync_component(
    spec: ComponentSpec,
    tools_dir: Path,
    *,
    env: dict[str, str] | None,
) -> tuple[ComponentResult, list[Diagnostic]]:
    if spec.deferred:
        return (
            ComponentResult(
                id=spec.id,
                status="deferred",
                pin=spec.pin,
                message="Ожидает реализации (#51)",
            ),
            [
                info(
                    f"Компонент {spec.id} отложен (docs facade → #51)",
                    code="1CT030",
                    source="toolchain",
                )
            ],
        )

    pin_short = spec.pin
    if spec.id == "xml-gen":
        path, diags = fetch_xml_gen(spec, tools_dir, env=env)
        pin_short = (spec.pin or "")[:12]
    elif spec.id == "md-reader":
        path, diags = fetch_md_reader(spec, tools_dir, env=env)
    elif spec.id == "bsl-language-server":
        path, diags = fetch_bsl_language_server(spec, tools_dir, env=env)
    else:
        return (
            ComponentResult(
                id=spec.id,
                status="skipped",
                pin=spec.pin,
                message=f"Неизвестный компонент: {spec.id}",
            ),
            [
                info(
                    f"Пропуск неизвестного компонента {spec.id}",
                    code="1CT031",
                    source="toolchain",
                )
            ],
        )

    if path is not None:
        return (
            ComponentResult(
                id=spec.id,
                status="ok",
                path=str(path),
                pin=pin_short,
            ),
            diags,
        )

    if spec.id in SOFT_IDS:
        return (
            ComponentResult(
                id=spec.id,
                status="warning",
                pin=pin_short,
                message="Не установлен (см. diagnostics)",
            ),
            diags,
        )
    return (
        ComponentResult(
            id=spec.id,
            status="error",
            pin=pin_short,
            message="Не установлен (см. diagnostics)",
        ),
        diags,
    )


def sync_tools(
    *,
    manifest: ToolchainManifest | None = None,
    env: dict[str, str] | None = None,
    cache_env: dict[str, str] | None = None,
) -> SyncResult:
    """Sync all manifest components into the user tools cache."""
    loaded = manifest if manifest is not None else load_manifest()
    tools_dir = tools_cache_dir(env=cache_env if cache_env is not None else env)
    tools_dir.mkdir(parents=True, exist_ok=True)

    components: list[ComponentResult] = []
    diagnostics: list[Diagnostic] = []

    for spec in loaded.components:
        result, diags = _sync_component(spec, tools_dir, env=env)
        components.append(result)
        diagnostics.extend(diags)

    must_failed = any(c.id in MUST_IDS and c.status == "error" for c in components)
    soft_failed = any(c.id in SOFT_IDS and c.status == "warning" for c in components)

    overall: OverallStatus
    if must_failed:
        overall = "error"
    elif soft_failed:
        overall = "degraded"
    else:
        overall = "ok"

    return SyncResult(status=overall, components=components, diagnostics=diagnostics)
