"""Orchestration: project.clean — wipe source.path + .runtime/ (ADR-021, #76)."""

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
    MANIFEST_NAME,
    RUNTIME_DIR_NAME,
)
from core.project.detect import detect_manifest
from core.project.load import load_manifest
from core.runtime.run import run_stop


def _source_dir_from_manifest(data: dict[str, Any], root: Path) -> Path:
    source_raw = data.get("source")
    source: dict[str, Any] = source_raw if isinstance(source_raw, dict) else {}
    source_rel = str(source.get("path") or "src/cf")
    return (root / source_rel).resolve()


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


def run_clean(
    start: Path | None = None,
    *,
    yes: bool = False,
    is_alive: IsRunningFn | None = None,
    terminate_fn: TerminateFn | None = None,
) -> CleanResult:
    """
    Wipe project source.path contents and entire .runtime/ (ADR-021).

    Requires yes=True. Does not touch manifest, AGENTS.md, IDE configs, git.
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
                    "Нужен флаг --yes (MCP: yes=true) для удаления source.path и .runtime/",
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
                    f"Файл {MANIFEST_NAME} не найден",
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
            root=manifest_path.parent,
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

    root = manifest_path.parent
    source_dir = _source_dir_from_manifest(data, root)
    runtime_dir = (root / RUNTIME_DIR_NAME).resolve()
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

    if runtime_dir.exists():
        try:
            shutil.rmtree(runtime_dir)
        except OSError as exc:
            return CleanResult(
                status="failed",
                duration=time.perf_counter() - started,
                root=root,
                source_path=source_dir,
                runtime_dir=runtime_dir,
                source_cleared=source_cleared,
                removed=removed,
                diagnostics=diagnostics
                + [
                    error(
                        f"Не удалось удалить {RUNTIME_DIR_NAME}/: {exc}",
                        code=CODE_CLEAN_FAILED,
                        source="runtime",
                    )
                ],
            )
        runtime_cleared = True
        removed.append(RUNTIME_DIR_NAME)
        diagnostics.append(
            info(
                f"Удалён каталог {RUNTIME_DIR_NAME}/",
                code=CODE_RUNTIME_CLEARED,
                source="runtime",
            )
        )

    if not source_cleared and not runtime_cleared:
        diagnostics.append(
            info(
                "Нечего удалять: source.path пуст, .runtime/ отсутствует",
                code=CODE_ALREADY_CLEAN,
                source="project",
            )
        )

    return CleanResult(
        status="ok",
        duration=time.perf_counter() - started,
        root=root,
        source_path=source_dir,
        runtime_dir=runtime_dir,
        source_cleared=source_cleared,
        runtime_cleared=runtime_cleared,
        removed=removed,
        diagnostics=diagnostics,
    )
