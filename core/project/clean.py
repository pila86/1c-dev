"""Orchestration: project.clean — wipe source + runtime (ADR-021/022 / #87)."""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any

from adapters.platform_1cv8 import IsRunningFn, TerminateFn, is_running
from core.diagnostics import error, info
from core.project.clean_result import CleanResult
from core.project.constants import (
    CODE_ALREADY_CLEAN,
    CODE_CLEAN_FAILED,
    CODE_CLIENT_RUNNING,
    CODE_CONFIRM_REQUIRED,
    CODE_MANIFEST_MISSING,
    CODE_RUNTIME_CLEARED,
    CODE_SOURCE_CLEARED,
    HOME_MANIFEST_REL,
    HOME_RUNTIME_DIR_NAME,
)
from core.project.detect import detect_project
from core.project.load import load_manifest
from core.project.paths import scope_root_from_manifest
from core.project.resolve import resolve_config_runtime
from core.runtime.run import run_stop


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _clear_directory_contents(directory: Path, *, root: Path) -> list[str]:
    """Remove all children of directory; leave (or create) empty dir. Return rel paths."""
    removed: list[str] = []
    if not directory.exists():
        directory.mkdir(parents=True, exist_ok=True)
        return removed
    if not directory.is_dir():
        raise OSError(f"source.path не каталог: {directory}")

    for child in sorted(directory.iterdir(), key=lambda p: p.name):
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink(missing_ok=False)
        removed.append(_rel(root, child))
    return removed


def _remove_tree_if_exists(
    directory: Path,
    *,
    root: Path,
    label: str,
) -> tuple[bool, list[str], list[Any]]:
    """Delete directory tree if present. Returns (cleared, removed, diagnostics)."""
    if not directory.exists():
        return False, [], []
    try:
        shutil.rmtree(directory)
    except OSError as exc:
        return (
            False,
            [],
            [
                error(
                    f"Не удалось удалить {label}: {exc}",
                    code=CODE_CLEAN_FAILED,
                    source="runtime",
                )
            ],
        )
    return True, [_rel(root, directory)], [
        info(
            f"Удалён каталог {label}",
            code=CODE_RUNTIME_CLEARED,
            source="runtime",
        )
    ]


def run_clean(
    start: Path | None = None,
    *,
    yes: bool = False,
    wipe_source: bool = True,
    config_id: str | None = None,
    runtime_id: str | None = None,
    is_alive: IsRunningFn | None = None,
    terminate_fn: TerminateFn | None = None,
) -> CleanResult:
    """
    Wipe project source (opt) and runtime (ADR-021/022 / #87).

    Without ``--config``/``--runtime``: wipe default configuration source and the
    entire ``.1c-dev/runtime/``.

    With ``--config`` and/or ``--runtime``: wipe resolved source and only the
    selected runtime path.

    Requires yes=True. Does not touch manifest, AGENTS.md, IDE configs, git.
    Stops a live runtime client first; refuses if stop fails.
    Idempotent when already empty.
    """
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    explicit_target = config_id is not None or runtime_id is not None

    if not yes:
        return CleanResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=start_path,
            diagnostics=[
                error(
                    "Нужен флаг --yes (MCP: yes=true) для удаления source и runtime",
                    code=CODE_CONFIRM_REQUIRED,
                    source="project",
                    suggestion="1c-dev project clean --yes",
                )
            ],
        )

    manifest = detect_project(start_path)
    if manifest.status != "ok" or manifest.path is None:
        return CleanResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=start_path,
            diagnostics=list(manifest.diagnostics)
            or [
                error(
                    f"Манифест проекта не найден ({HOME_MANIFEST_REL})",
                    code=CODE_MANIFEST_MISSING,
                    source="project",
                    suggestion="Выполните 1c-dev init или configuration import",
                )
            ],
        )
    manifest_path = manifest.path

    data, load_diags = load_manifest(manifest_path)
    if data is None:
        return CleanResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=scope_root_from_manifest(manifest_path),
            diagnostics=list(load_diags)
            or [
                error(
                    "Не удалось прочитать манифест",
                    code=CODE_MANIFEST_MISSING,
                    file=str(manifest_path.name),
                    source="project",
                )
            ],
        )

    root = scope_root_from_manifest(manifest_path)
    target, resolve_diags = resolve_config_runtime(
        data,
        config_id=config_id,
        runtime_id=runtime_id,
        require_runtime=explicit_target,
    )
    if target is None:
        return CleanResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            diagnostics=list(resolve_diags)
            or [
                error(
                    "Не удалось разрешить --config/--runtime",
                    code=CODE_MANIFEST_MISSING,
                    source="project",
                )
            ],
        )

    if explicit_target:
        if target.runtime_rel is None:
            return CleanResult(
                status="failed",
                duration=time.perf_counter() - started,
                root=root,
                diagnostics=[
                    error(
                        "Не удалось разрешить runtime для clean",
                        code=CODE_MANIFEST_MISSING,
                        source="project",
                    )
                ],
            )
        stop_config_id: str | None = target.config_id
        stop_runtime_id: str | None = target.runtime_id
        report_runtime = (root / target.runtime_rel).resolve()
    else:
        stop_config_id = None
        stop_runtime_id = None
        report_runtime = (root / HOME_RUNTIME_DIR_NAME).resolve()

    source_dir = (root / target.source_rel).resolve()
    home_runtime = (root / HOME_RUNTIME_DIR_NAME).resolve()
    runtime_dir = report_runtime if explicit_target else home_runtime

    diagnostics: list[Any] = []
    removed: list[str] = []

    # Refuse to wipe project root or paths outside the project.
    try:
        source_dir.relative_to(root)
    except ValueError:
        return CleanResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            source_path=source_dir,
            runtime_dir=runtime_dir,
            diagnostics=[
                error(
                    f"source.path вне каталога проекта: {source_dir}",
                    code=CODE_CLEAN_FAILED,
                    source="project",
                )
            ],
        )
    if source_dir == root:
        return CleanResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            source_path=source_dir,
            runtime_dir=runtime_dir,
            diagnostics=[
                error(
                    "source.path совпадает с корнем проекта — отказ от wipe",
                    code=CODE_CLEAN_FAILED,
                    source="project",
                )
            ],
        )

    alive = is_alive or is_running
    stop_result = run_stop(
        root,
        config_id=stop_config_id,
        runtime_id=stop_runtime_id,
        is_alive=alive,
        terminate_fn=terminate_fn,
    )
    if stop_result.status != "ok":
        diagnostics.extend(stop_result.diagnostics)
        diagnostics.append(
            error(
                "Не удалось остановить runtime-клиент перед project.clean",
                code=CODE_CLIENT_RUNNING,
                source="runtime",
                suggestion="1c-dev runtime stop",
            )
        )
        return CleanResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            source_path=source_dir,
            runtime_dir=runtime_dir,
            diagnostics=diagnostics,
        )

    source_cleared = False
    runtime_cleared = False

    if wipe_source:
        try:
            source_removed = _clear_directory_contents(source_dir, root=root)
        except OSError as exc:
            return CleanResult(
                status="failed",
                duration=time.perf_counter() - started,
                root=root,
                source_path=source_dir,
                runtime_dir=runtime_dir,
                diagnostics=[
                    error(
                        f"Не удалось очистить source.path {source_dir}: {exc}",
                        code=CODE_CLEAN_FAILED,
                        source="project",
                    )
                ],
            )

        if source_removed:
            source_cleared = True
            removed.extend(source_removed)
            diagnostics.append(
                info(
                    f"Очищен source.path: {_rel(root, source_dir)} "
                    f"({len(source_removed)} элемент(ов))",
                    code=CODE_SOURCE_CLEARED,
                    source="project",
                )
            )

    if explicit_target:
        cleared, cleared_paths, clear_diags = _remove_tree_if_exists(
            report_runtime,
            root=root,
            label=_rel(root, report_runtime),
        )
        diagnostics.extend(clear_diags)
        if any(d.get("severity") == "error" for d in clear_diags):
            return CleanResult(
                status="failed",
                duration=time.perf_counter() - started,
                root=root,
                source_path=source_dir,
                runtime_dir=runtime_dir,
                source_cleared=source_cleared,
                removed=removed,
                diagnostics=diagnostics,
            )
        if cleared:
            runtime_cleared = True
            removed.extend(cleared_paths)
    else:
        cleared, cleared_paths, clear_diags = _remove_tree_if_exists(
            home_runtime, root=root, label=f"{HOME_RUNTIME_DIR_NAME}/"
        )
        diagnostics.extend(clear_diags)
        if any(d.get("severity") == "error" for d in clear_diags):
            return CleanResult(
                status="failed",
                duration=time.perf_counter() - started,
                root=root,
                source_path=source_dir,
                runtime_dir=runtime_dir,
                source_cleared=source_cleared,
                removed=removed,
                diagnostics=diagnostics,
            )
        if cleared:
            runtime_cleared = True
            removed.extend(cleared_paths)

    if not source_cleared and not runtime_cleared:
        if explicit_target:
            msg = (
                "Нечего удалять: source пуст (или wipe_source=false), "
                f"runtime {_rel(root, report_runtime)} отсутствует"
            )
        else:
            msg = (
                "Нечего удалять: source пуст (или wipe_source=false), "
                f"{HOME_RUNTIME_DIR_NAME}/ отсутствует"
            )
        diagnostics.append(
            info(
                msg,
                code=CODE_ALREADY_CLEAN,
                source="project",
            )
        )

    return CleanResult(
        status="ok",
        duration=time.perf_counter() - started,
        root=root,
        source_path=source_dir,
        runtime_dir=runtime_dir if explicit_target else home_runtime,
        source_cleared=source_cleared,
        runtime_cleared=runtime_cleared,
        removed=removed,
        diagnostics=diagnostics,
    )
