"""Locate project manifest: ``.1c-dev/project.yaml`` or legacy ``1c.project.yaml``."""

from __future__ import annotations

from pathlib import Path

from core.diagnostics import error, warning
from core.project.constants import (
    CODE_LEGACY_MANIFEST,
    DEFAULT_LIST_DEPTH,
    HOME_DIR_NAME,
    HOME_MANIFEST_NAME,
    HOME_MANIFEST_REL,
    LEGACY_MANIFEST_NAME,
    MANIFEST_NAME,
)
from core.project.load import load_manifest
from core.project.paths import (
    is_home_manifest,
    project_home,
    runtimes_summary,
    scope_root_from_manifest,
)
from core.project.result import ProjectResult

__all__ = [
    "MANIFEST_NAME",
    "detect_manifest",
    "detect_project",
    "list_projects",
    "scope_root_from_manifest",
]


def _prefer_home_then_legacy(directory: Path) -> tuple[Path | None, bool]:
    """Return (manifest_path, is_legacy) for a single directory."""
    home = directory / HOME_DIR_NAME / HOME_MANIFEST_NAME
    if home.is_file():
        return home, False
    legacy = directory / LEGACY_MANIFEST_NAME
    if legacy.is_file():
        return legacy, True
    return None, False


def detect_manifest(start: Path | None = None) -> Path | None:
    """Искать манифест от start (по умолчанию CWD) вверх по родителям.

    Сначала ``.1c-dev/project.yaml``, иначе legacy ``1c.project.yaml``.

    Returns:
        Абсолютный путь к найденному файлу или None.
    """
    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        path, _legacy = _prefer_home_then_legacy(directory)
        if path is not None:
            return path
    return None


def detect_project(start: Path | None = None) -> ProjectResult:
    """Найти манифест; при успехе вернуть path/root/home и краткие поля."""
    path = detect_manifest(start)
    if path is None:
        return ProjectResult(
            status="error",
            diagnostics=[
                error(
                    f"Манифест проекта не найден "
                    f"({HOME_MANIFEST_REL} или {LEGACY_MANIFEST_NAME})",
                    code="1CP001",
                    file=HOME_MANIFEST_REL,
                )
            ],
        )

    root = scope_root_from_manifest(path)
    home = project_home(root) if is_home_manifest(path) else None
    diagnostics = []
    if not is_home_manifest(path):
        diagnostics.append(
            warning(
                f"Обнаружен legacy манифест {LEGACY_MANIFEST_NAME}; "
                f"предпочтителен layout {HOME_MANIFEST_REL} (schema \"2\")",
                code=CODE_LEGACY_MANIFEST,
                file=LEGACY_MANIFEST_NAME,
                source="project",
                suggestion="1c-dev project migrate (should) или init в новом scope",
            )
        )

    data, _ = load_manifest(path)
    return ProjectResult(
        status="ok",
        path=path,
        root=root,
        home=home,
        manifest=data,
        diagnostics=diagnostics,
        runtimes=runtimes_summary(data) if data else [],
    )


def list_projects(
    start: Path | None = None,
    *,
    max_depth: int = DEFAULT_LIST_DEPTH,
) -> list[ProjectResult]:
    """Сканировать вниз от start в поисках ``.1c-dev/project.yaml`` (monorepo).

    Ограничение глубины относительно start. Legacy корневые манифесты не ищет.
    """
    root = (start or Path.cwd()).resolve()
    if not root.is_dir():
        return []

    skip_dirs = {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".tox",
        "build",
        "dist",
        HOME_DIR_NAME,
        ".runtime",
        ".cache",
    }

    found: list[ProjectResult] = []
    # depth 0 = root itself
    stack: list[tuple[Path, int]] = [(root, 0)]
    seen: set[Path] = set()

    while stack:
        directory, depth = stack.pop()
        try:
            resolved = directory.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)

        candidate = resolved / HOME_DIR_NAME / HOME_MANIFEST_NAME
        if candidate.is_file():
            scope = resolved
            data, _ = load_manifest(candidate)
            found.append(
                ProjectResult(
                    status="ok",
                    path=candidate,
                    root=scope,
                    home=project_home(scope),
                    manifest=data,
                    runtimes=runtimes_summary(data) if data else [],
                )
            )
            # Не спускаемся внутрь найденного scope (избегаем дублей).
            continue

        if depth >= max_depth:
            continue

        try:
            children = sorted(resolved.iterdir(), key=lambda p: p.name)
        except OSError:
            continue

        for child in children:
            if not child.is_dir() or child.is_symlink():
                continue
            name = child.name
            if name in skip_dirs or name.startswith("."):
                # Allow descending into non-dot product dirs only; skip all dot-dirs
                # except we already handled .1c-dev via candidate check.
                continue
            stack.append((child, depth + 1))

    found.sort(key=lambda r: str(r.root or ""))
    return found
