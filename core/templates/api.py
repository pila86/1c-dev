"""Platform templates API: roots / list / get (ADR-024 / #91)."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from adapters.platform.templates import TemplateRootsResult, discover_template_roots
from core.diagnostics import Diagnostic, error, warning
from core.templates.mft import MftManifest, parse_mft_file, source_kind

Status = Literal["ok", "error"]

CODE_NOT_FOUND = "1CT001"
CODE_ROOTS_EMPTY = "1CT002"

SOURCE_HINT = (
    "Установите шаблоны конфигураций платформы (tmplts) "
    "или задайте ConfigurationTemplatesLocation в 1cestart.cfg."
)


@dataclass(frozen=True)
class TemplateInfo:
    """One listable template entry (mft section with Source)."""

    id: str
    vendor: str | None
    name: str | None
    version: str | None
    app_version: str | None
    section: str
    catalog: str | None
    destination: str | None
    source: str | None
    source_kind: str | None
    source_path: Path | None
    mft_path: Path
    root: Path

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "vendor": self.vendor,
            "name": self.name,
            "version": self.version,
            "appVersion": self.app_version,
            "section": self.section,
            "catalog": self.catalog,
            "destination": self.destination,
            "source": self.source,
            "sourceKind": self.source_kind,
            "sourcePath": str(self.source_path) if self.source_path else None,
            "mftPath": str(self.mft_path),
            "root": str(self.root),
        }


@dataclass
class TemplatesRootsResult:
    """Result of templates.roots."""

    status: Status
    roots: list[Path] = field(default_factory=list)
    configured: list[Path] = field(default_factory=list)
    cfg_paths: list[Path] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "roots": [str(p) for p in self.roots],
            "configured": [str(p) for p in self.configured],
            "cfgPaths": [str(p) for p in self.cfg_paths],
        }
        if self.diagnostics:
            payload["diagnostics"] = list(self.diagnostics)
        return payload


@dataclass
class TemplatesListResult:
    """Result of templates.list."""

    status: Status
    templates: list[TemplateInfo] = field(default_factory=list)
    roots: list[Path] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "roots": [str(p) for p in self.roots],
            "templates": [t.to_payload() for t in self.templates],
        }
        if self.diagnostics:
            payload["diagnostics"] = list(self.diagnostics)
        return payload


@dataclass
class TemplatesGetResult:
    """Result of templates.get."""

    status: Status
    template: TemplateInfo | None = None
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": self.status}
        if self.template is not None:
            payload["template"] = self.template.to_payload()
        if self.diagnostics:
            payload["diagnostics"] = list(self.diagnostics)
        return payload


DiscoverRootsFn = Callable[..., TemplateRootsResult]


def make_template_id(mft_path: Path, section: str) -> str:
    """Stable id from absolute mft path + section (ADR-024)."""
    key = f"{mft_path.resolve().as_posix()}|{section}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def _resolve_source_path(mft_path: Path, source: str | None) -> Path | None:
    if not source:
        return None
    candidate = (mft_path.parent / source).resolve()
    return candidate if candidate.is_file() else candidate


def _entries_from_manifest(manifest: MftManifest, root: Path) -> list[TemplateInfo]:
    items: list[TemplateInfo] = []
    for section in manifest.sections:
        tid = make_template_id(manifest.path, section.name)
        items.append(
            TemplateInfo(
                id=tid,
                vendor=manifest.vendor,
                name=manifest.name,
                version=manifest.version,
                app_version=manifest.app_version,
                section=section.name,
                catalog=section.catalog,
                destination=section.destination,
                source=section.source,
                source_kind=source_kind(section.source),
                source_path=_resolve_source_path(manifest.path, section.source),
                mft_path=manifest.path,
                root=root,
            )
        )
    return items


def iter_mft_files(roots: Iterable[Path]) -> list[tuple[Path, Path]]:
    """Return (root, mft_path) pairs for all *.mft under roots (recursive)."""
    found: list[tuple[Path, Path]] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            continue
        root_r = root.resolve()
        for mft in sorted(root_r.rglob("*.mft")):
            if not mft.is_file():
                continue
            resolved = mft.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            found.append((root_r, resolved))
    return found


def collect_templates(
    roots: Iterable[Path],
) -> list[TemplateInfo]:
    """Scan roots for *.mft and build TemplateInfo list (one per section)."""
    templates: list[TemplateInfo] = []
    for root, mft_path in iter_mft_files(roots):
        try:
            manifest = parse_mft_file(mft_path)
        except OSError:
            continue
        templates.extend(_entries_from_manifest(manifest, root))
    return templates


def templates_roots(
    *,
    discover: DiscoverRootsFn | None = None,
    cfg_paths: list[Path] | None = None,
    default_roots: list[Path] | None = None,
) -> TemplatesRootsResult:
    """List discovered tmplts roots (cfg + defaults)."""
    fn = discover or discover_template_roots
    result = fn(cfg_paths=cfg_paths, default_roots=default_roots)
    diagnostics: list[Diagnostic] = []
    if not result.roots:
        diagnostics.append(
            warning(
                "Каталог шаблонов платформы (tmplts) не найден",
                code=CODE_ROOTS_EMPTY,
                source="templates",
                suggestion=SOURCE_HINT,
            )
        )
    return TemplatesRootsResult(
        status="ok",
        roots=list(result.roots),
        configured=list(result.configured),
        cfg_paths=list(result.cfg_paths),
        diagnostics=diagnostics,
    )


def templates_list(
    *,
    vendor: str | None = None,
    name: str | None = None,
    version: str | None = None,
    source_kind_filter: str | None = None,
    query: str | None = None,
    discover: DiscoverRootsFn | None = None,
    cfg_paths: list[Path] | None = None,
    default_roots: list[Path] | None = None,
    roots: list[Path] | None = None,
) -> TemplatesListResult:
    """List templates from discovered (or injected) tmplts roots."""
    if roots is None:
        fn = discover or discover_template_roots
        discovered = fn(cfg_paths=cfg_paths, default_roots=default_roots)
        use_roots = list(discovered.roots)
    else:
        use_roots = [p.resolve() for p in roots]

    diagnostics: list[Diagnostic] = []
    if not use_roots:
        diagnostics.append(
            warning(
                "Каталог шаблонов платформы (tmplts) не найден — список пуст",
                code=CODE_ROOTS_EMPTY,
                source="templates",
                suggestion=SOURCE_HINT,
            )
        )
        return TemplatesListResult(
            status="ok",
            templates=[],
            roots=[],
            diagnostics=diagnostics,
        )

    templates = collect_templates(use_roots)

    def match(t: TemplateInfo) -> bool:
        if vendor and (t.vendor or "").casefold() != vendor.casefold():
            return False
        if name and (t.name or "").casefold() != name.casefold():
            return False
        if version and (t.version or "").casefold() != version.casefold():
            return False
        if source_kind_filter and (t.source_kind or "") != source_kind_filter.casefold():
            return False
        if query:
            q = query.casefold()
            hay = " ".join(
                filter(
                    None,
                    [
                        t.vendor,
                        t.name,
                        t.version,
                        t.catalog,
                        t.destination,
                        t.section,
                        t.source,
                    ],
                )
            ).casefold()
            if q not in hay:
                return False
        return True

    filtered = [t for t in templates if match(t)]
    return TemplatesListResult(
        status="ok",
        templates=filtered,
        roots=use_roots,
        diagnostics=diagnostics,
    )


def templates_get(
    template_id: str,
    *,
    discover: DiscoverRootsFn | None = None,
    cfg_paths: list[Path] | None = None,
    default_roots: list[Path] | None = None,
    roots: list[Path] | None = None,
) -> TemplatesGetResult:
    """Get one template by stable id from the current discovery set."""
    tid = template_id.strip()
    if not tid:
        return TemplatesGetResult(
            status="error",
            diagnostics=[
                error(
                    "Не указан id шаблона",
                    code=CODE_NOT_FOUND,
                    source="templates",
                    suggestion="Вызовите templates.list и передайте id из результата.",
                )
            ],
        )

    listed = templates_list(
        discover=discover,
        cfg_paths=cfg_paths,
        default_roots=default_roots,
        roots=roots,
    )
    for item in listed.templates:
        if item.id == tid:
            return TemplatesGetResult(status="ok", template=item)

    return TemplatesGetResult(
        status="error",
        diagnostics=[
            error(
                f"Шаблон не найден: {tid}",
                code=CODE_NOT_FOUND,
                source="templates",
                suggestion="Вызовите templates.list и используйте актуальный id.",
            )
        ],
    )
