"""Build orchestration: project + ibcmd adapter (ADR-008)."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from adapters.platform import DiscoveryResult, discover_environment
from adapters.platform_ibcmd import IbcmdError, RunFn, build_with_ibcmd
from adapters.platform_ibcmd.constants import (
    CODE_ARTIFACT,
    CODE_IBCMD_MISSING,
    CODE_PROJECT,
    CODE_SOURCE_FORMAT,
    CODE_SOURCE_MISSING,
    DEFAULT_ARTIFACT_REL,
    IBCMD_DATA_REL,
)
from core.build.result import BuildResult
from core.diagnostics import error
from core.project.detect import detect_manifest
from core.project.load import load_manifest

BuildFn = Callable[..., list[str]]


def run_build(
    start: Path | None = None,
    *,
    artifact: str | None = None,
    run: RunFn | None = None,
    build_fn: BuildFn | None = None,
    discover: Callable[[], DiscoveryResult] | None = None,
) -> BuildResult:
    """
    Load XML configuration into file IB via ibcmd.

    artifact: None | \"cf\"
    run / build_fn / discover: injectable for tests.
    """
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()

    if artifact is not None and artifact != "cf":
        return BuildResult(
            status="failed",
            duration=time.perf_counter() - started,
            diagnostics=[
                error(
                    f"Неизвестный тип артефакта: {artifact}",
                    code=CODE_ARTIFACT,
                    source="runtime",
                    suggestion="Используйте --artifact cf или опустите флаг",
                )
            ],
        )

    manifest_path = detect_manifest(start_path)
    if manifest_path is None:
        return BuildResult(
            status="failed",
            duration=time.perf_counter() - started,
            diagnostics=[
                error(
                    "Файл 1c.project.yaml не найден",
                    code=CODE_PROJECT,
                    source="runtime",
                    suggestion="Выполните 1c-dev init --type configuration",
                )
            ],
        )

    data, load_diags = load_manifest(manifest_path)
    if data is None:
        return BuildResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=manifest_path.parent,
            diagnostics=list(load_diags)
            or [
                error(
                    "Не удалось прочитать манифест",
                    code=CODE_PROJECT,
                    file=str(manifest_path.name),
                    source="runtime",
                )
            ],
        )

    root = manifest_path.parent
    source_raw = data.get("source")
    source: dict[str, Any] = source_raw if isinstance(source_raw, dict) else {}
    runtime_raw = data.get("runtime")
    runtime: dict[str, Any] = runtime_raw if isinstance(runtime_raw, dict) else {}

    fmt = source.get("format")
    if fmt != "xml":
        return BuildResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            diagnostics=[
                error(
                    f"source.format={fmt!r}: M1 build поддерживает только xml",
                    code=CODE_SOURCE_FORMAT,
                    file=manifest_path.name,
                    source="runtime",
                )
            ],
        )

    source_rel = str(source.get("path") or "src/cf")
    source_dir = (root / source_rel).resolve()
    if not source_dir.is_dir():
        return BuildResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            diagnostics=[
                error(
                    f"Каталог исходников не найден: {source_rel}",
                    code=CODE_SOURCE_MISSING,
                    source="runtime",
                )
            ],
        )

    runtime_rel = str(runtime.get("path") or ".runtime/ib")
    db_path = (root / runtime_rel).resolve()
    data_path = (root / IBCMD_DATA_REL).resolve()

    discovery = (discover or discover_environment)()
    ibcmd_info = discovery.ibcmd
    if not ibcmd_info.found or ibcmd_info.path is None:
        return BuildResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            runtime_path=db_path,
            diagnostics=[
                error(
                    "ibcmd не найден",
                    code=CODE_IBCMD_MISSING,
                    source="platform",
                    suggestion=(
                        "Установите платформу 1С и добавьте ibcmd в PATH "
                        "(или в стандартный каталог установки)."
                    ),
                )
            ],
        )

    cf_path: Path | None = None
    artifact_rel: str | None = None
    if artifact == "cf":
        artifact_rel = DEFAULT_ARTIFACT_REL
        cf_path = (root / artifact_rel).resolve()

    try:
        if build_fn is not None:
            steps = build_fn(
                ibcmd_info.path,
                db_path=db_path,
                data_path=data_path,
                source_dir=source_dir,
                cf_path=cf_path,
                run=run,
            )
        else:
            steps = build_with_ibcmd(
                ibcmd_info.path,
                db_path=db_path,
                data_path=data_path,
                source_dir=source_dir,
                cf_path=cf_path,
                run=run,
            )
    except IbcmdError as exc:
        return BuildResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            runtime_path=db_path,
            steps=[],
            diagnostics=list(exc.diagnostics)
            or [
                error(
                    exc.message,
                    code=exc.code,
                    source="platform",
                )
            ],
        )

    return BuildResult(
        status="ok",
        duration=time.perf_counter() - started,
        root=root,
        runtime_path=db_path,
        artifact=artifact_rel,
        steps=list(steps),
    )
