"""Orchestration: project.clean — wipe source + ``.1c-dev/runtime/`` (ADR-021/022)."""

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
    LEGACY_MANIFEST_NAME,
    LEGACY_RUNTIME_DIR_NAME,
)
from core.project.detect import detect_manifest
from core.project.load import load_manifest
from core.project.paths import default_source_rel, scope_root_from_manifest
from core.runtime.run import run_stop


def _source_dir_from_manifest(data: dict[str, Any], root: Path) -> Path:
    return (root / default_source_rel(data)).resolve()


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
    is_alive: IsRunningFn | None = None,
    terminate_fn: TerminateFn | None = None,
) -> CleanResult:
    """
    Wipe project source (opt) and runtime home ``.1c-dev/runtime/`` (ADR-021/022).

    Also removes legacy ``.runtime/`` if present. Requires yes=True.
    Does not touch manifest, AGENTS.md, IDE configs, git.
    Stops a live runtime client first; refuses if stop fails.
    Idempotent when already empty.
    """
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()

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

    manifest_path = detect_manifest(start_path)
    if manifest_path is None:
        return CleanResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=start_path,
            diagnostics=[
                error(
                    f"Манифест проекта не найден "
                    f"({HOME_MANIFEST_REL} или {LEGACY_MANIFEST_NAME})",
                    code=CODE_MANIFEST_MISSING,
                    source="project",
                    suggestion="Выполните 1c-dev init или project import",
                )
            ],
        )

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
    source_dir = _source_dir_from_manifest(data, root)
    home_runtime = (root / HOME_RUNTIME_DIR_NAME).resolve()
    legacy_runtime = (root / LEGACY_RUNTIME_DIR_NAME).resolve()
    # Primary runtime dir reported in result: home layout preferred.
    if home_runtime.exists() or not legacy_runtime.exists():
        runtime_dir = home_runtime
    else:
        runtime_dir = legacy_runtime
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

    for label, directory in (
        (HOME_RUNTIME_DIR_NAME, home_runtime),
        (LEGACY_RUNTIME_DIR_NAME, legacy_runtime),
    ):
        cleared, cleared_paths, clear_diags = _remove_tree_if_exists(
            directory, root=root, label=f"{label}/"
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
        diagnostics.append(
            info(
                "Нечего удалять: source пуст (или wipe_source=false), "
                f"{HOME_RUNTIME_DIR_NAME}/ и {LEGACY_RUNTIME_DIR_NAME}/ отсутствуют",
                code=CODE_ALREADY_CLEAN,
                source="project",
            )
        )

    return CleanResult(
        status="ok",
        duration=time.perf_counter() - started,
        root=root,
        source_path=source_dir,
        runtime_dir=home_runtime,
        source_cleared=source_cleared,
        runtime_cleared=runtime_cleared,
        removed=removed,
        diagnostics=diagnostics,
    )
