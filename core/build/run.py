"""Build orchestration: project + ibcmd adapter (ADR-008)."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

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
from core.diagnostics import Diagnostic, error
from core.project.constants import HOME_MANIFEST_REL
from core.project.detect import detect_manifest
from core.project.load import load_manifest
from core.project.paths import scope_root_from_manifest
from core.project.resolve import resolve_config_runtime

BuildFn = Callable[..., list[str]]


def _nested_extensions(
    configuration: dict[str, object],
    *,
    root: Path,
) -> tuple[list[tuple[str, Path]], list[Diagnostic]]:
    """
    Collect nested extensions[] for build.

    Returns (extensions as (name, abs_source_dir), diagnostics on error).
    """
    raw = configuration.get("extensions")
    if not isinstance(raw, list) or not raw:
        return [], []

    result: list[tuple[str, Path]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name:
            return [], [
                error(
                    "extensions[].name обязателен для build",
                    code=CODE_PROJECT,
                    source="runtime",
                )
            ]
        source = item.get("source")
        if not isinstance(source, dict):
            return [], [
                error(
                    f"extensions[{name!r}]: отсутствует source",
                    code=CODE_SOURCE_MISSING,
                    source="runtime",
                )
            ]
        fmt = source.get("format")
        if fmt != "xml":
            return [], [
                error(
                    f"extensions[{name!r}]: source.format={fmt!r}; "
                    "build поддерживает только xml",
                    code=CODE_SOURCE_FORMAT,
                    source="runtime",
                )
            ]
        path = source.get("path")
        if not isinstance(path, str) or not path:
            return [], [
                error(
                    f"extensions[{name!r}]: отсутствует source.path",
                    code=CODE_SOURCE_MISSING,
                    source="runtime",
                )
            ]
        ext_dir = (root / path).resolve()
        if not ext_dir.is_dir():
            return [], [
                error(
                    f"Каталог исходников расширения не найден: {path}",
                    code=CODE_SOURCE_MISSING,
                    source="runtime",
                )
            ]
        result.append((name, ext_dir))
    return result, []


def _primary_extension_name(
    data: dict[str, object],
    configuration: dict[str, object],
) -> str | None:
    """ibcmd --extension for standalone configurations[].type=extension."""
    if configuration.get("type") != "extension":
        return None
    project = data.get("project")
    if isinstance(project, dict):
        pname = project.get("name")
        if isinstance(pname, str) and pname:
            return pname
    cid = configuration.get("id")
    if isinstance(cid, str) and cid:
        return cid
    return None


def run_build(
    start: Path | None = None,
    *,
    artifact: str | None = None,
    config_id: str | None = None,
    runtime_id: str | None = None,
    run: RunFn | None = None,
    build_fn: BuildFn | None = None,
    discover: Callable[[], DiscoveryResult] | None = None,
) -> BuildResult:
    """
    Load XML configuration (then nested extensions) into file IB via ibcmd.

    artifact: None | \"cf\"
    config_id / runtime_id: selection from configurations[] / runtimes[] (#87).
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
                    f"Файл {HOME_MANIFEST_REL} не найден",
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
            root=scope_root_from_manifest(manifest_path),
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

    root = scope_root_from_manifest(manifest_path)

    target, resolve_diags = resolve_config_runtime(
        data,
        config_id=config_id,
        runtime_id=runtime_id,
        require_runtime=True,
    )
    if target is None or target.runtime_rel is None:
        return BuildResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            diagnostics=list(resolve_diags)
            or [
                error(
                    "Не удалось разрешить --config/--runtime",
                    code=CODE_PROJECT,
                    source="runtime",
                )
            ],
        )

    fmt = target.source_format
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

    source_rel = target.source_rel
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

    primary_extension = _primary_extension_name(data, target.configuration)
    extensions, ext_diags = _nested_extensions(target.configuration, root=root)
    if ext_diags:
        return BuildResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            diagnostics=list(ext_diags),
        )

    runtime_rel = target.runtime_rel
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
                primary_extension=primary_extension,
                extensions=extensions,
                run=run,
            )
        else:
            steps = build_with_ibcmd(
                ibcmd_info.path,
                db_path=db_path,
                data_path=data_path,
                source_dir=source_dir,
                cf_path=cf_path,
                primary_extension=primary_extension,
                extensions=extensions,
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
