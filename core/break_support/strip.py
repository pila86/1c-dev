"""Source-level strip of ParentConfigurations* support artifacts (ADR-020)."""

from __future__ import annotations

import shutil
from pathlib import Path

from core.break_support.constants import CODE_ALREADY_OFF_SUPPORT, CODE_SUPPORT_REMOVED
from core.diagnostics import Diagnostic, info, warning


def _is_support_artifact_name(name: str) -> bool:
    return name == "ParentConfigurations" or name.startswith("ParentConfigurations.")


def collect_support_artifacts(source_dir: Path) -> list[Path]:
    """
    Find support artifacts under source_dir without touching metadata objects.

    Looks in source root and Ext/ for ParentConfigurations / ParentConfigurations.*.
    """
    candidates: list[Path] = []
    search_roots = [source_dir, source_dir / "Ext"]
    for root in search_roots:
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir(), key=lambda p: p.name):
            if _is_support_artifact_name(child.name):
                candidates.append(child)
    return candidates


def _rel_to(path: Path, base: Path) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return str(path)


def strip_parent_configurations(
    source_dir: Path,
    *,
    root: Path | None = None,
) -> tuple[list[str], list[Diagnostic]]:
    """
    Delete ParentConfigurations* artifacts under source_dir.

    Idempotent: no artifacts → empty removed + warning diagnostic.
    Returns (removed relative paths, diagnostics). Paths are relative to root
    when possible, otherwise to source_dir.
    """
    base = root if root is not None else source_dir
    removed: list[str] = []
    diagnostics: list[Diagnostic] = []

    for path in collect_support_artifacts(source_dir):
        rel = _rel_to(path, base)
        if path.is_dir():
            shutil.rmtree(path)
        elif path.is_file() or path.is_symlink():
            path.unlink()
        else:
            continue
        removed.append(rel)
        diagnostics.append(
            info(
                f"Удалён артефакт поддержки: {rel}",
                code=CODE_SUPPORT_REMOVED,
                file=rel,
                source="runtime",
            )
        )

    if not removed:
        diagnostics.append(
            warning(
                "Конфигурация уже снята с поддержки "
                "(артефакты ParentConfigurations* не найдены)",
                code=CODE_ALREADY_OFF_SUPPORT,
                source="runtime",
            )
        )

    return removed, diagnostics
