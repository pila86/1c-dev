"""Discover XML/EDT configuration and extension roots in a scope (ADR-034)."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from adapters.source.edt.detect import (
    configuration_mdo_path,
    is_edt_project_root,
    read_edt_project_name,
)
from adapters.source.xml.detect import configuration_xml_path, is_xml_source_root
from core.diagnostics import Diagnostic, warning
from core.project.init import sanitize_ext_id, sanitize_project_name
from core.test.discover import module_has_executable_scenarios

SourceFormat = Literal["xml", "edt"]
SourceKind = Literal["configuration", "extension"]

SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".1c-dev",
        "build",
        ".runtime",
        ".cache",
        "node_modules",
        ".venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        "dist",
        ".idea",
        ".vscode",
    }
)

_TEST_NAME_MARKERS = ("test", "tests", "yaxunit", "юнит")
_XML_NAME_RE = re.compile(r"<Name>\s*([^<]+?)\s*</Name>", re.IGNORECASE)
_XML_NAME_PREFIX_RE = re.compile(
    r"<NamePrefix>\s*([^<]*?)\s*</NamePrefix>", re.IGNORECASE
)
# 0=scope root; 3 covers common ``src/cfe/<ext>`` and ``docs/…/cf`` layouts.
_MAX_DEPTH = 3


@dataclass(frozen=True)
class DiscoveredSource:
    """One detected configuration or extension root."""

    path: Path
    rel_path: str
    format: SourceFormat
    kind: SourceKind
    name: str
    suggested_id: str
    purpose: str | None = None  # product | tests for extensions
    parent_config_rel: str | None = None


@dataclass
class DiscoverSourcesResult:
    """Result of scanning a scope for 1C sources."""

    configurations: list[DiscoveredSource] = field(default_factory=list)
    extensions: list[DiscoveredSource] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)


def _should_skip_dir(name: str) -> bool:
    if name in SKIP_DIR_NAMES:
        return True
    if name.startswith(".") and name not in {".project", ".settings"}:
        # Skip hidden dirs at walk level; markers live as files inside candidates.
        return True
    return False


def _iter_candidate_dirs(root: Path, *, max_depth: int = _MAX_DEPTH) -> list[Path]:
    """Breadth-limited directory walk (depth 0 = root itself)."""
    root = root.resolve()
    found: list[Path] = [root]
    frontier: list[tuple[Path, int]] = [(root, 0)]
    while frontier:
        current, depth = frontier.pop(0)
        if depth >= max_depth:
            continue
        try:
            children = sorted(current.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            continue
        for child in children:
            if not child.is_dir():
                continue
            if _should_skip_dir(child.name):
                continue
            found.append(child.resolve())
            frontier.append((child.resolve(), depth + 1))
    return found


def _rel_posix(root: Path, path: Path) -> str:
    try:
        rel = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()
    return rel if rel != "." else "."


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8-sig")
    except OSError:
        return None


def _local_tag(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _xml_properties_text(cfg_xml: Path) -> str | None:
    return _read_text(cfg_xml)


def _xml_element_text(text: str, local_name: str) -> str | None:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        # Fallback regex for Name only.
        if local_name == "Name":
            match = _XML_NAME_RE.search(text)
            return match.group(1).strip() if match else None
        if local_name == "NamePrefix":
            match = _XML_NAME_PREFIX_RE.search(text)
            return match.group(1).strip() if match else None
        return None

    for el in root.iter():
        if _local_tag(el.tag) != "Properties":
            continue
        for child in el:
            if _local_tag(child.tag) == local_name:
                return (child.text or "").strip()
    # Some dumps put Name outside Properties — scan all.
    for el in root.iter():
        if _local_tag(el.tag) == local_name and el.text is not None:
            # Prefer first Properties-scoped; if none, first match.
            value = el.text.strip()
            if value or local_name == "NamePrefix":
                return value
    return None


def _is_xml_extension(cfg_xml: Path) -> bool:
    text = _xml_properties_text(cfg_xml)
    if text is None:
        return False
    if "ObjectBelonging" in text and "Adopted" in text:
        # Cheap check then precise.
        belonging = _xml_element_text(text, "ObjectBelonging")
        if belonging == "Adopted":
            return True
    purpose = _xml_element_text(text, "ConfigurationExtensionPurpose")
    if purpose:
        return True
    prefix = _xml_element_text(text, "NamePrefix")
    if prefix:
        return True
    return False


def _xml_name(cfg_xml: Path) -> str | None:
    text = _xml_properties_text(cfg_xml)
    if text is None:
        return None
    return _xml_element_text(text, "Name")


def _is_edt_extension(project_root: Path) -> bool:
    mdo = configuration_mdo_path(project_root)
    text = _read_text(mdo) if mdo.is_file() else None
    if text is None:
        return False
    lowered = text.lower()
    markers = (
        "configurationextensionpurpose",
        "nameprefix",
        "objectbelonging",
        "<extension>",
    )
    if any(m in lowered for m in markers):
        # Empty namePrefix tag alone is weak; require non-empty content or purpose.
        if "configurationextensionpurpose" in lowered:
            return True
        if re.search(r"<namePrefix>\s*[^<\s]+", text, re.IGNORECASE):
            return True
        if re.search(r"<objectBelonging>\s*Adopted", text, re.IGNORECASE):
            return True
    return False


def _edt_name(project_root: Path) -> str | None:
    name = read_edt_project_name(project_root)
    if name:
        return name
    mdo = configuration_mdo_path(project_root)
    text = _read_text(mdo) if mdo.is_file() else None
    if text is None:
        return None
    match = re.search(r"<name>\s*([^<]+?)\s*</name>", text, re.IGNORECASE)
    return match.group(1).strip() if match else None


def _common_module_bsl_roots(ext_root: Path, fmt: SourceFormat) -> list[Path]:
    """Roots that may contain CommonModules/*/…/Module.bsl."""
    if fmt == "xml":
        return [ext_root]
    # EDT: modules under src/
    return [ext_root / "src", ext_root]


def _extension_has_executable_scenarios(ext_root: Path, fmt: SourceFormat) -> bool:
    for base in _common_module_bsl_roots(ext_root, fmt):
        common = base / "CommonModules"
        if not common.is_dir():
            continue
        try:
            children = list(common.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir():
                continue
            candidates = [
                child / "Ext" / "Module.bsl",
                child / "Module.bsl",
            ]
            for bsl in candidates:
                if not bsl.is_file():
                    continue
                text = _read_text(bsl)
                if text and module_has_executable_scenarios(text):
                    return True
    return False


def _looks_like_test_name(name: str, suggested_id: str) -> bool:
    blob = f"{name} {suggested_id}".lower()
    return any(marker in blob for marker in _TEST_NAME_MARKERS)


def _unique_id(base: str, used: set[str], *, ext: bool) -> str:
    sanitize = sanitize_ext_id if ext else sanitize_project_name
    candidate = sanitize(base)
    if candidate not in used:
        used.add(candidate)
        return candidate
    n = 2
    while True:
        nxt = f"{candidate}_{n}"
        if nxt not in used:
            used.add(nxt)
            return nxt
        n += 1


def _normalize_edt_candidate(path: Path) -> Path | None:
    """Return EDT project root or None."""
    resolved = path.resolve()
    if is_edt_project_root(resolved):
        return resolved
    # Walk found src/ with Configuration/Configuration.mdo → parent.
    if (resolved / "Configuration" / "Configuration.mdo").is_file():
        parent = resolved.parent
        if is_edt_project_root(parent):
            return parent
        # Bare src-like without .project still treat parent as root if mdo path matches.
        if resolved.name == "src":
            return parent
        return parent
    return None


def _nearest_config_rel(
    ext_rel: str,
    config_rels: list[str],
) -> str | None:
    if not config_rels:
        return None
    if len(config_rels) == 1:
        return config_rels[0]

    ext_parts = Path(ext_rel).parts
    best: str | None = None
    best_score = -1
    for conf_rel in config_rels:
        conf_parts = Path(conf_rel).parts
        # Shared parent prefix length.
        common = 0
        for a, b in zip(ext_parts, conf_parts, strict=False):
            if a != b:
                break
            common += 1
        # Prefer sibling under same parent (score by common + proximity).
        score = common * 10
        if conf_rel != "." and ext_rel != ".":
            if Path(ext_rel).parent == Path(conf_rel).parent:
                score += 5
            if Path(conf_rel) in Path(ext_rel).parents or Path(ext_rel).parent == Path(
                conf_rel
            ):
                score += 3
        if score > best_score:
            best_score = score
            best = conf_rel
    return best or config_rels[0]


def _collect_raw_candidates(
    root: Path,
    *,
    max_depth: int = _MAX_DEPTH,
) -> tuple[list[tuple[Path, SourceFormat]], list[Diagnostic]]:
    """Find unique XML/EDT roots under root."""
    diags: list[Diagnostic] = []
    xml_roots: set[Path] = set()
    edt_roots: set[Path] = set()

    for candidate in _iter_candidate_dirs(root, max_depth=max_depth):
        if is_xml_source_root(candidate):
            xml_roots.add(candidate.resolve())
            continue
        edt = _normalize_edt_candidate(candidate)
        if edt is not None:
            edt_roots.add(edt.resolve())

    # Prefer EDT over XML when XML root lives inside an EDT project tree.
    filtered_xml: set[Path] = set()
    for xml_root in xml_roots:
        inside_edt = False
        for edt_root in edt_roots:
            try:
                xml_root.relative_to(edt_root)
                inside_edt = True
                break
            except ValueError:
                continue
        if not inside_edt:
            filtered_xml.add(xml_root)

    out: list[tuple[Path, SourceFormat]] = [
        *((p, "xml") for p in sorted(filtered_xml)),
        *((p, "edt") for p in sorted(edt_roots)),
    ]
    return out, diags


def discover_sources(root: Path, *, max_depth: int = _MAX_DEPTH) -> DiscoverSourcesResult:
    """
    Scan ``root`` for Designer XML / EDT configuration and extension roots.

    Depth 0–``max_depth`` (default 2). Does not write the manifest.
    """
    scope = root.resolve()
    result = DiscoverSourcesResult()
    raw, raw_diags = _collect_raw_candidates(scope, max_depth=max_depth)
    result.diagnostics.extend(raw_diags)

    used_ids: set[str] = set()
    configs: list[DiscoveredSource] = []
    exts: list[DiscoveredSource] = []

    classified: list[tuple[Path, SourceFormat, SourceKind, str]] = []
    for path, fmt in raw:
        if fmt == "xml":
            cfg_xml = configuration_xml_path(path)
            name = _xml_name(cfg_xml) or path.name
            kind: SourceKind = "extension" if _is_xml_extension(cfg_xml) else "configuration"
        else:
            name = _edt_name(path) or path.name
            if _is_edt_extension(path):
                kind = "extension"
            else:
                kind = "configuration"
        classified.append((path, fmt, kind, name))

    # If we have both kinds, reclassify ambiguous EDT "configuration" that sit
    # next to a clear conf as extensions only when already marked — no invent.

    for path, fmt, kind, name in classified:
        if kind == "configuration":
            suggested = _unique_id(name, used_ids, ext=False)
            configs.append(
                DiscoveredSource(
                    path=path,
                    rel_path=_rel_posix(scope, path),
                    format=fmt,
                    kind="configuration",
                    name=name,
                    suggested_id=suggested,
                )
            )
        else:
            suggested = _unique_id(name, used_ids, ext=True)
            purpose = "product"
            if _extension_has_executable_scenarios(path, fmt) or _looks_like_test_name(
                name, suggested
            ):
                purpose = "tests"
            exts.append(
                DiscoveredSource(
                    path=path,
                    rel_path=_rel_posix(scope, path),
                    format=fmt,
                    kind="extension",
                    name=name,
                    suggested_id=suggested,
                    purpose=purpose,
                )
            )

    if exts and not configs:
        result.diagnostics.append(
            warning(
                "Найдены расширения без configuration — adopt пропущен",
                code="1CP030",
                suggestion=(
                    "Добавьте configuration (configuration.add) или положите "
                    "исходники conf в scope, затем повторите init --force"
                ),
            )
        )
        result.extensions = []
        result.configurations = []
        return result

    config_rels = [c.rel_path for c in configs]
    bound_exts: list[DiscoveredSource] = []
    for ext in exts:
        parent = _nearest_config_rel(ext.rel_path, config_rels)
        if parent is None:
            continue
        if len(config_rels) > 1 and parent == config_rels[0]:
            # Soft note only when scoring was weak — always attach, warn once.
            pass
        bound_exts.append(
            DiscoveredSource(
                path=ext.path,
                rel_path=ext.rel_path,
                format=ext.format,
                kind=ext.kind,
                name=ext.name,
                suggested_id=ext.suggested_id,
                purpose=ext.purpose,
                parent_config_rel=parent,
            )
        )

    if len(config_rels) > 1 and bound_exts:
        ambiguous = [
            e
            for e in bound_exts
            if e.parent_config_rel == configs[0].rel_path
            and Path(e.rel_path).parent != Path(configs[0].rel_path).parent
        ]
        if ambiguous:
            result.diagnostics.append(
                warning(
                    "Несколько configuration: часть extensions привязана к default "
                    f"({configs[0].suggested_id}) по эвристике",
                    code="1CP031",
                    suggestion="Проверьте configurations[].extensions[] в манифесте",
                )
            )

    result.configurations = configs
    result.extensions = bound_exts
    return result
