"""Locate 1c.project.yaml from a starting directory upward."""

from __future__ import annotations

from pathlib import Path

from core.diagnostics import error
from core.project.constants import MANIFEST_NAME
from core.project.load import load_manifest
from core.project.result import ProjectResult

__all__ = ["MANIFEST_NAME", "detect_manifest", "detect_project"]


def detect_manifest(start: Path | None = None) -> Path | None:
    """Искать манифест от start (по умолчанию CWD) вверх по родителям.

    Returns:
        Абсолютный путь к найденному файлу или None.
    """
    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        candidate = directory / MANIFEST_NAME
        if candidate.is_file():
            return candidate
    return None


def detect_project(start: Path | None = None) -> ProjectResult:
    """Найти манифест; при успехе вернуть path/root и краткие поля, если YAML парсится."""
    path = detect_manifest(start)
    if path is None:
        return ProjectResult(
            status="error",
            diagnostics=[
                error(
                    f"Файл {MANIFEST_NAME} не найден",
                    code="1CP001",
                    file=MANIFEST_NAME,
                )
            ],
        )

    data, _ = load_manifest(path)
    return ProjectResult(
        status="ok",
        path=path,
        root=path.parent,
        manifest=data,
    )
