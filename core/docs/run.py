"""docs.search / docs.get orchestration (ADR-017 / #51)."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from adapters.docs import (
    DOCS_INDEX_DIR_ENV,
    DocsFacadeError,
    ensure_index,
    fetch_script_suggestion,
    find_hbk,
    get_index_entry,
    search_index,
)
from adapters.platform import discover_environment
from core.diagnostics import Diagnostic, error, info
from core.docs.result import DocsResult
from core.project.detect import detect_manifest
from core.project.init import platform_version_for_manifest
from core.project.load import load_manifest
from core.toolchain.cache import docs_cache_dir

Op = Literal["search", "get"]
EnsureFn = Callable[..., dict[str, Any]]
SearchFn = Callable[..., dict[str, Any]]
GetFn = Callable[..., dict[str, Any]]


def _project_context(start: Path | None) -> DocsResult | tuple[Path, str]:
    """Resolve project root and platform.version from manifest."""
    start_path = (start or Path.cwd()).resolve()
    manifest_path = detect_manifest(start_path)
    if manifest_path is None:
        return DocsResult(
            status="error",
            diagnostics=[
                error(
                    "Файл 1c.project.yaml не найден",
                    code="1CX001",
                    source="docs",
                    suggestion="Выполните 1c-dev init --type configuration",
                )
            ],
        )

    data, load_diags = load_manifest(manifest_path)
    if data is None:
        return DocsResult(
            status="error",
            root=manifest_path.parent,
            diagnostics=list(load_diags)
            or [
                error(
                    "Не удалось прочитать манифест",
                    code="1CX001",
                    file=str(manifest_path),
                    source="docs",
                )
            ],
        )

    root = manifest_path.parent
    platform_raw = data.get("platform")
    platform: dict[str, Any] = platform_raw if isinstance(platform_raw, dict) else {}
    version = platform_version_for_manifest(
        str(platform.get("version")) if platform.get("version") else None
    )
    return root, version


def _index_dir_for(version: str, *, env: dict[str, str] | None = None) -> Path:
    environ = env if env is not None else dict(os.environ)
    override = environ.get(DOCS_INDEX_DIR_ENV, "").strip()
    if override:
        return Path(override).expanduser().resolve() / version
    return docs_cache_dir(env=environ) / version


def _ensure_ready(
    *,
    root: Path,
    platform_version: str,
    env: dict[str, str] | None,
    ensure_fn: EnsureFn,
) -> DocsResult | tuple[Path, bool, list[Diagnostic]]:
    """Locate HBK and ensure index; return (index_dir, built, diags) or error result."""
    diagnostics: list[Diagnostic] = []
    discovery = discover_environment()
    hbk = find_hbk(discovery.platform.path, env=env)
    if not hbk.found or hbk.path is None:
        return DocsResult(
            status="error",
            root=root,
            platform_version=platform_version,
            diagnostics=[
                error(
                    "HBK синтакс-помощника не найден (shcntx_ru.hbk)",
                    code="1CX002",
                    source="docs",
                    suggestion=(
                        "Установите платформу 1С или задайте ONEC_HBK_PATH "
                        "на shcntx_ru.hbk."
                    ),
                )
            ],
        )

    index_dir = _index_dir_for(platform_version, env=env)
    index_dir.mkdir(parents=True, exist_ok=True)
    meta = index_dir / "meta.json"
    needs_build = not meta.is_file()
    if needs_build:
        diagnostics.append(
            info(
                f"Строим индекс документации для {platform_version}…",
                code="1CX010",
                source="docs",
            )
        )

    try:
        payload = ensure_fn(
            index_dir=index_dir,
            platform_version=platform_version,
            hbk=hbk.path,
        )
    except DocsFacadeError as exc:
        return DocsResult(
            status="error",
            root=root,
            platform_version=platform_version,
            index_path=index_dir,
            diagnostics=[
                *diagnostics,
                error(
                    exc.message,
                    code=exc.code,
                    source="docs",
                    suggestion=fetch_script_suggestion()
                    if exc.code == "1CX001"
                    else None,
                ),
            ],
        )

    index_info_raw = payload.get("index")
    index_info = index_info_raw if isinstance(index_info_raw, dict) else {}
    built = bool(index_info.get("built")) or needs_build
    return index_dir, built, diagnostics


def search_docs(
    start: Path | None,
    query: str,
    *,
    limit: int = 20,
    env: dict[str, str] | None = None,
    ensure_fn: EnsureFn | None = None,
    search_fn: SearchFn | None = None,
) -> DocsResult:
    """Search platform documentation index for query."""
    ctx = _project_context(start)
    if isinstance(ctx, DocsResult):
        return ctx
    root, platform_version = ctx

    if not query or not query.strip():
        return DocsResult(
            status="error",
            root=root,
            platform_version=platform_version,
            diagnostics=[
                error(
                    "Пустой поисковый запрос",
                    code="1CX003",
                    source="docs",
                )
            ],
        )

    ready = _ensure_ready(
        root=root,
        platform_version=platform_version,
        env=env,
        ensure_fn=ensure_fn or ensure_index,
    )
    if isinstance(ready, DocsResult):
        return ready
    index_dir, built, diags = ready

    try:
        payload = (search_fn or search_index)(
            index_dir=index_dir,
            query=query.strip(),
            limit=limit,
        )
    except DocsFacadeError as exc:
        return DocsResult(
            status="error",
            root=root,
            platform_version=platform_version,
            index_path=index_dir,
            index_built=built,
            diagnostics=[
                *diags,
                error(exc.message, code=exc.code, source="docs"),
            ],
        )

    hits_raw = payload.get("hits")
    hits: list[dict[str, Any]] = (
        [h for h in hits_raw if isinstance(h, dict)] if isinstance(hits_raw, list) else []
    )
    return DocsResult(
        status="ok",
        root=root,
        platform_version=platform_version,
        index_path=index_dir,
        index_built=built,
        hits=hits,
        diagnostics=diags,
    )


def get_docs(
    start: Path | None,
    name: str,
    *,
    env: dict[str, str] | None = None,
    ensure_fn: EnsureFn | None = None,
    get_fn: GetFn | None = None,
) -> DocsResult:
    """Get a documentation entry by name or Owner.Member."""
    ctx = _project_context(start)
    if isinstance(ctx, DocsResult):
        return ctx
    root, platform_version = ctx

    if not name or not name.strip():
        return DocsResult(
            status="error",
            root=root,
            platform_version=platform_version,
            diagnostics=[
                error(
                    "Пустое имя записи",
                    code="1CX003",
                    source="docs",
                )
            ],
        )

    ready = _ensure_ready(
        root=root,
        platform_version=platform_version,
        env=env,
        ensure_fn=ensure_fn or ensure_index,
    )
    if isinstance(ready, DocsResult):
        return ready
    index_dir, built, diags = ready

    try:
        payload = (get_fn or get_index_entry)(
            index_dir=index_dir,
            name=name.strip(),
        )
    except DocsFacadeError as exc:
        return DocsResult(
            status="error",
            root=root,
            platform_version=platform_version,
            index_path=index_dir,
            index_built=built,
            diagnostics=[
                *diags,
                error(exc.message, code=exc.code, source="docs"),
            ],
        )

    entry_raw = payload.get("entry")
    entry = entry_raw if isinstance(entry_raw, dict) else None
    return DocsResult(
        status="ok",
        root=root,
        platform_version=platform_version,
        index_path=index_dir,
        index_built=built,
        entry=entry,
        diagnostics=diags,
    )
