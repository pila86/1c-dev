"""Idempotent toolchain sync (`1c-dev tools sync`)."""

from __future__ import annotations

from pathlib import Path

from core.diagnostics import Diagnostic, info
from core.toolchain.cache import tools_cache_dir
from core.toolchain.fetchers.bslls import fetch_bsl_language_server
from core.toolchain.fetchers.docsfacade import fetch_docs_facade
from core.toolchain.fetchers.mdreader import fetch_md_reader
from core.toolchain.fetchers.xmlgen import fetch_xml_gen
from core.toolchain.manifest import ComponentSpec, ToolchainManifest, load_manifest
from core.toolchain.progress import ProgressFn, noop_progress
from core.toolchain.result import ComponentResult, OverallStatus, SyncResult

MUST_IDS = frozenset({"xml-gen", "md-reader"})
SOFT_IDS = frozenset({"bsl-language-server", "docs-facade"})


def _sync_component(
    spec: ComponentSpec,
    tools_dir: Path,
    *,
    env: dict[str, str] | None,
    progress: ProgressFn,
    quiet: bool,
) -> tuple[ComponentResult, list[Diagnostic]]:
    if spec.deferred:
        progress(f"→ {spec.id}: deferred")
        return (
            ComponentResult(
                id=spec.id,
                status="deferred",
                pin=spec.pin,
                message="Ожидает реализации",
            ),
            [
                info(
                    f"Компонент {spec.id} отложен",
                    code="1CT030",
                    source="toolchain",
                )
            ],
        )

    pin_short = spec.pin
    if spec.id == "xml-gen":
        path, diags = fetch_xml_gen(
            spec, tools_dir, env=env, progress=progress, quiet=quiet
        )
        pin_short = (spec.pin or "")[:12]
    elif spec.id == "md-reader":
        path, diags = fetch_md_reader(
            spec, tools_dir, env=env, progress=progress, quiet=quiet
        )
    elif spec.id == "bsl-language-server":
        path, diags = fetch_bsl_language_server(
            spec, tools_dir, env=env, progress=progress, quiet=quiet
        )
    elif spec.id == "docs-facade":
        path, diags = fetch_docs_facade(
            spec, tools_dir, env=env, progress=progress, quiet=quiet
        )
    else:
        progress(f"→ {spec.id}: skipped")
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
        progress(f"✓ {spec.id}: ok")
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
        progress(f"! {spec.id}: warning")
        return (
            ComponentResult(
                id=spec.id,
                status="warning",
                pin=pin_short,
                message="Не установлен (см. diagnostics)",
            ),
            diags,
        )
    progress(f"✗ {spec.id}: error")
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
    progress: ProgressFn | None = None,
    quiet: bool = True,
) -> SyncResult:
    """Sync all manifest components into the user tools cache."""
    report = progress or noop_progress
    loaded = manifest if manifest is not None else load_manifest()
    tools_dir = tools_cache_dir(env=cache_env if cache_env is not None else env)
    tools_dir.mkdir(parents=True, exist_ok=True)

    report("Toolchain sync…")

    components: list[ComponentResult] = []
    diagnostics: list[Diagnostic] = []

    for spec in loaded.components:
        result, diags = _sync_component(
            spec,
            tools_dir,
            env=env,
            progress=report,
            quiet=quiet,
        )
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
