"""Orchestration: source break-support (ADR-020, #74)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from core.break_support.constants import CODE_PROJECT
from core.break_support.result import BreakSupportResult
from core.break_support.strip import strip_parent_configurations
from core.diagnostics import error
from core.project.constants import MANIFEST_NAME
from core.project.detect import detect_manifest
from core.project.load import load_manifest


def _source_dir_from_manifest(data: dict[str, Any], root: Path) -> Path:
    source_raw = data.get("source")
    source: dict[str, Any] = source_raw if isinstance(source_raw, dict) else {}
    source_rel = str(source.get("path") or "src/cf")
    return (root / source_rel).resolve()


def run_break_support(start: Path | None = None) -> BreakSupportResult:
    """
    Strip ParentConfigurations* from project source.path (no import).

    Requires an existing 1c.project.yaml. Idempotent.
    """
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()

    manifest_path = detect_manifest(start_path)
    if manifest_path is None:
        return BreakSupportResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=start_path,
            diagnostics=[
                error(
                    f"Файл {MANIFEST_NAME} не найден",
                    code=CODE_PROJECT,
                    source="runtime",
                    suggestion="Выполните 1c-dev init или project import",
                )
            ],
        )

    data, load_diags = load_manifest(manifest_path)
    if data is None:
        return BreakSupportResult(
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
    source_dir = _source_dir_from_manifest(data, root)
    removed, diags = strip_parent_configurations(source_dir, root=root)
    return BreakSupportResult(
        status="ok",
        duration=time.perf_counter() - started,
        root=root,
        source_path=source_dir,
        removed=removed,
        diagnostics=diags,
    )
