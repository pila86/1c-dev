"""Locate project manifest: ``.1c-dev/project.yaml`` only (ADR-022)."""

from __future__ import annotations

from pathlib import Path

from core.diagnostics import error
from core.project.constants import (
    CODE_LEGACY_MANIFEST,
    DEFAULT_LIST_DEPTH,
    HOME_DIR_NAME,
    HOME_MANIFEST_NAME,
    HOME_MANIFEST_REL,
    MANIFEST_NAME,
    UNSUPPORTED_ROOT_MANIFEST_NAME,
)
from core.project.load import load_manifest
from core.project.paths import (
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


def _home_manifest(directory: Path) -> Path | None:
    home = directory / HOME_DIR_NAME / HOME_MANIFEST_NAME
    return home if home.is_file() else None


def _unsupported_root_manifest(directory: Path) -> Path | None:
    legacy = directory / UNSUPPORTED_ROOT_MANIFEST_NAME
    return legacy if legacy.is_file() else None


def detect_manifest(start: Path | None = None) -> Path | None:
    """Искать ``.1c-dev/project.yaml`` от start (по умолчанию CWD) вверх.

    Returns:
        Абсолютный путь к найденному файлу или None.
    """
    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        path = _home_manifest(directory)
        if path is not None:
            return path
    return None


def _find_unsupported_root(start: Path | None = None) -> Path | None:
    """Если home нет, но вверх есть корневой ``1c.project.yaml`` — вернуть его."""
    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        if _home_manifest(directory) is not None:
            return None
        legacy = _unsupported_root_manifest(directory)
        if legacy is not None:
            return legacy
    return None


def detect_project(start: Path | None = None) -> ProjectResult:
    """Найти манифест; при успехе вернуть path/root/home и краткие поля."""
    path = detect_manifest(start)
    if path is None:
        unsupported = _find_unsupported_root(start)
        if unsupported is not None:
            return ProjectResult(
                status="error",
                path=unsupported,
                root=unsupported.parent,
                diagnostics=[
                    error(
                        f"Корневой манифест {UNSUPPORTED_ROOT_MANIFEST_NAME} "
                        f"больше не поддерживается; нужен layout "
                        f"{HOME_MANIFEST_REL} (schema \"2\")",
                        code=CODE_LEGACY_MANIFEST,
                        file=UNSUPPORTED_ROOT_MANIFEST_NAME,
                        source="project",
                        suggestion="1c-dev project init",
                    )
                ],
            )
        return ProjectResult(
            status="error",
            diagnostics=[
                error(
                    f"Манифест проекта не найден ({HOME_MANIFEST_REL})",
                    code="1CP001",
                    file=HOME_MANIFEST_REL,
                )
            ],
        )

    root = scope_root_from_manifest(path)
    data, _ = load_manifest(path)
    return ProjectResult(
        status="ok",
        path=path,
        root=root,
        home=project_home(root),
        manifest=data,
        diagnostics=[],
        runtimes=runtimes_summary(data) if data else [],
    )


def list_projects(
    start: Path | None = None,
    *,
    max_depth: int = DEFAULT_LIST_DEPTH,
) -> list[ProjectResult]:
    """Сканировать вниз от start в поисках ``.1c-dev/project.yaml`` (monorepo).

    Ограничение глубины относительно start.
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
