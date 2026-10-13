"""Module UUID index from XML source (+ extensions) with disk cache (#139/#145).

Scans Designer XML dumps: ``CommonModules/*.xml``, ``Ext/*ApplicationModule.bsl``,
and object modules (``Catalogs|Documents|…/Name/Ext/ObjectModule.bsl`` etc.).
Cache: ``.1c-dev/debug/modules-cache.json`` (mtime fingerprint invalidate).
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from adapters.debug_http.constants import (
    DEBUG_STATE_DIR_NAME,
    MODULE_PROPERTY_IDS,
    MODULES_CACHE_FILENAME,
    MODULES_CACHE_VERSION,
    PROPERTY_ID_APPLICATION_MODULE,
    PROPERTY_ID_COMMON_MODULE,
)
from core.metadata.types import TYPE_DIRS
from core.project.constants import HOME_DIR_NAME

# Folders that own ObjectModule / ManagerModule / RecordSetModule under Ext/
_OBJECT_MODULE_FOLDERS: frozenset[str] = frozenset(
    {
        "Catalogs",
        "Documents",
        "ExchangePlans",
        "ChartsOfAccounts",
        "ChartsOfCharacteristicTypes",
        "ChartsOfCalculationTypes",
        "BusinessProcesses",
        "Tasks",
        "Reports",
        "DataProcessors",
    }
)
_RECORD_SET_FOLDERS: frozenset[str] = frozenset(
    {
        "InformationRegisters",
        "AccumulationRegisters",
        "AccountingRegisters",
        "CalculationRegisters",
    }
)
_OWNED_MODULE_FILES: dict[str, str] = {
    "ObjectModule.bsl": "ObjectModule",
    "ManagerModule.bsl": "ManagerModule",
    "RecordSetModule.bsl": "RecordSetModule",
}
_APP_MODULE_FILES: dict[str, str] = {
    "ManagedApplicationModule.bsl": "ManagedApplicationModule",
    "OrdinaryApplicationModule.bsl": "ApplicationModule",
    "ApplicationModule.bsl": "ApplicationModule",
}


@dataclass(frozen=True)
class SourceRoot:
    """One XML source tree: main configuration or an extension."""

    path: Path
    extension_name: str = ""  # empty = main configuration


@dataclass(frozen=True)
class ModuleIndexEntry:
    """One indexed module (objectID + propertyID)."""

    module_name: str
    module_type: str
    object_id: str
    property_id: str
    extension_name: str = ""
    source_file: str = ""


@dataclass
class ModulesIndex:
    """In-memory module UUID index."""

    modules: list[ModuleIndexEntry] = field(default_factory=list)
    roots: list[dict[str, Any]] = field(default_factory=list)
    built_at: str = ""

    def find(
        self,
        module_name: str,
        module_type: str,
        *,
        extension_name: str | None = None,
        any_extension: bool = False,
    ) -> list[ModuleIndexEntry]:
        """Return matching entries (may be empty or ambiguous).

        ``extension_name=""`` — only main configuration.
        ``any_extension=True`` — only modules that belong to some extension
        (ignores ``extension_name``).
        """
        want_ext = extension_name or ""
        type_aliases = _type_aliases(module_type)
        out: list[ModuleIndexEntry] = []
        seen: set[tuple[str, str, str]] = set()
        for entry in self.modules:
            if any_extension:
                if not entry.extension_name:
                    continue
            elif entry.extension_name != want_ext:
                continue
            if entry.module_type not in type_aliases:
                continue
            if not _name_matches(module_name, module_type, entry):
                continue
            key = (entry.object_id, entry.property_id, entry.extension_name)
            if key in seen:
                continue
            seen.add(key)
            out.append(entry)
        return out

    def find_by_source_file(
        self,
        source_file: str,
        *,
        extension_name: str | None = None,
        any_extension: bool = False,
    ) -> list[ModuleIndexEntry]:
        """Match by relative ``sourceFile`` (posix, case-sensitive)."""
        want = source_file.replace("\\", "/")
        want_ext = extension_name or ""
        out: list[ModuleIndexEntry] = []
        for entry in self.modules:
            if any_extension:
                if not entry.extension_name:
                    continue
            elif entry.extension_name != want_ext:
                continue
            if entry.source_file.replace("\\", "/") == want:
                out.append(entry)
        return out


def modules_cache_path(scope_root: Path) -> Path:
    """``<scope>/.1c-dev/debug/modules-cache.json``."""
    return scope_root / HOME_DIR_NAME / DEBUG_STATE_DIR_NAME / MODULES_CACHE_FILENAME


def debug_state_dir(scope_root: Path) -> Path:
    """``<scope>/.1c-dev/debug/``."""
    return scope_root / HOME_DIR_NAME / DEBUG_STATE_DIR_NAME


def source_roots_from_configuration(
    scope_root: Path,
    configuration: dict[str, Any],
) -> list[SourceRoot]:
    """Build ``SourceRoot`` list from a ``configurations[]`` entry."""
    roots: list[SourceRoot] = []
    source = configuration.get("source")
    if isinstance(source, dict):
        path = source.get("path")
        if isinstance(path, str) and path:
            roots.append(SourceRoot(path=(scope_root / path).resolve(), extension_name=""))
    extensions = configuration.get("extensions")
    if isinstance(extensions, list):
        for ext in extensions:
            if not isinstance(ext, dict):
                continue
            ext_source = ext.get("source")
            if not isinstance(ext_source, dict):
                continue
            ext_path = ext_source.get("path")
            if not isinstance(ext_path, str) or not ext_path:
                continue
            name = ext.get("name")
            if not isinstance(name, str) or not name:
                ext_id = ext.get("id")
                name = ext_id if isinstance(ext_id, str) else ""
            if not name:
                continue
            roots.append(
                SourceRoot(
                    path=(scope_root / ext_path).resolve(),
                    extension_name=name,
                )
            )
    return roots


def scan_source_root(root: Path, *, extension_name: str = "") -> list[ModuleIndexEntry]:
    """Scan one XML source tree for Common / Application / object modules."""
    if not root.is_dir():
        return []
    entries: list[ModuleIndexEntry] = []
    entries.extend(_scan_common_modules(root, extension_name=extension_name))
    entries.extend(_scan_application_modules(root, extension_name=extension_name))
    entries.extend(_scan_owned_modules(root, extension_name=extension_name))
    return entries


def build_modules_index(roots: Sequence[SourceRoot]) -> ModulesIndex:
    """Scan all roots and return a fresh index (no disk I/O)."""
    modules: list[ModuleIndexEntry] = []
    root_meta: list[dict[str, Any]] = []
    for src in roots:
        path = src.path.resolve()
        scanned = scan_source_root(path, extension_name=src.extension_name)
        modules.extend(scanned)
        root_meta.append(
            {
                "path": str(path),
                "extensionName": src.extension_name,
                "fingerprint": _root_fingerprint(path),
            }
        )
    return ModulesIndex(
        modules=modules,
        roots=root_meta,
        built_at=_now_iso(),
    )


def load_or_build_index(
    scope_root: Path,
    roots: Sequence[SourceRoot],
    *,
    cache_path: Path | None = None,
    force: bool = False,
) -> ModulesIndex:
    """Load cache if fingerprints match; otherwise rebuild and save."""
    path = cache_path or modules_cache_path(scope_root)
    if not force:
        cached = _try_load_cache(path, roots)
        if cached is not None:
            return cached
    index = build_modules_index(roots)
    save_modules_cache(path, index)
    return index


def reload_metadata(
    scope_root: Path,
    roots: Sequence[SourceRoot],
    *,
    cache_path: Path | None = None,
) -> ModulesIndex:
    """Force rebuild of UUID↔module cache (``debug.reloadMetadata``)."""
    return load_or_build_index(
        scope_root, roots, cache_path=cache_path, force=True
    )


def save_modules_cache(cache_path: Path, index: ModulesIndex) -> None:
    """Write ``modules-cache.json``."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    modules_out: list[dict[str, Any]] = [
        {
            "moduleName": m.module_name,
            "moduleType": m.module_type,
            "objectId": m.object_id,
            "propertyId": m.property_id,
            "extensionName": m.extension_name,
            "sourceFile": m.source_file,
        }
        for m in index.modules
    ]
    payload = {
        "version": MODULES_CACHE_VERSION,
        "builtAt": index.built_at or _now_iso(),
        "roots": index.roots,
        "modules": modules_out,
    }
    cache_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_modules_cache(cache_path: Path) -> ModulesIndex | None:
    """Parse cache file; return None if missing/invalid."""
    if not cache_path.is_file():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("version") != MODULES_CACHE_VERSION:
        return None
    modules_raw = data.get("modules")
    if not isinstance(modules_raw, list):
        return None
    modules: list[ModuleIndexEntry] = []
    for item in modules_raw:
        if not isinstance(item, dict):
            continue
        try:
            modules.append(
                ModuleIndexEntry(
                    module_name=str(item["moduleName"]),
                    module_type=str(item["moduleType"]),
                    object_id=str(item["objectId"]),
                    property_id=str(item["propertyId"]),
                    extension_name=str(item.get("extensionName") or ""),
                    source_file=str(item.get("sourceFile") or ""),
                )
            )
        except (KeyError, TypeError):
            continue
    roots = data.get("roots")
    return ModulesIndex(
        modules=modules,
        roots=roots if isinstance(roots, list) else [],
        built_at=str(data.get("builtAt") or ""),
    )


# --- internals ---------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _text(el: ET.Element | None) -> str:
    if el is None or el.text is None:
        return ""
    return el.text.strip()


def _find_child(parent: ET.Element, name: str) -> ET.Element | None:
    for child in parent:
        if _local(child.tag) == name:
            return child
    return None


def _find_desc(parent: ET.Element, name: str) -> ET.Element | None:
    for el in parent.iter():
        if _local(el.tag) == name:
            return el
    return None


def _root_fingerprint(root: Path) -> float:
    """Max mtime of metadata files that affect module UUIDs."""
    candidates: list[float] = []
    cfg = root / "Configuration.xml"
    if cfg.is_file():
        candidates.append(cfg.stat().st_mtime)
    common = root / "CommonModules"
    if common.is_dir():
        for p in common.glob("*.xml"):
            candidates.append(p.stat().st_mtime)
        for p in common.glob("*/Ext/*.bsl"):
            candidates.append(p.stat().st_mtime)
    ext = root / "Ext"
    if ext.is_dir():
        for p in ext.glob("*.bsl"):
            candidates.append(p.stat().st_mtime)
    for folder in _OBJECT_MODULE_FOLDERS | _RECORD_SET_FOLDERS:
        base = root / folder
        if not base.is_dir():
            continue
        for p in base.glob("*.xml"):
            candidates.append(p.stat().st_mtime)
        for p in base.glob("*/Ext/*.bsl"):
            candidates.append(p.stat().st_mtime)
    return max(candidates) if candidates else 0.0


def _try_load_cache(
    cache_path: Path, roots: Sequence[SourceRoot]
) -> ModulesIndex | None:
    cached = load_modules_cache(cache_path)
    if cached is None:
        return None
    expected: list[tuple[str, str, float]] = []
    for src in roots:
        resolved = src.path.resolve()
        expected.append(
            (str(resolved), src.extension_name, _root_fingerprint(resolved))
        )
    cached_roots = cached.roots
    if len(cached_roots) != len(expected):
        return None
    for meta, (exp_path, exp_ext, exp_fp) in zip(
        cached_roots, expected, strict=True
    ):
        if not isinstance(meta, dict):
            return None
        if str(meta.get("path") or "") != exp_path:
            return None
        if str(meta.get("extensionName") or "") != exp_ext:
            return None
        try:
            cached_fp = float(meta.get("fingerprint") or 0.0)
        except (TypeError, ValueError):
            return None
        if abs(cached_fp - exp_fp) > 1e-6:
            return None
    return cached


def _scan_common_modules(
    root: Path, *, extension_name: str
) -> list[ModuleIndexEntry]:
    common = root / "CommonModules"
    if not common.is_dir():
        return []
    property_id = MODULE_PROPERTY_IDS.get("CommonModule", PROPERTY_ID_COMMON_MODULE)
    out: list[ModuleIndexEntry] = []
    for xml_path in sorted(common.glob("*.xml")):
        parsed = _parse_md_object_xml(xml_path, "CommonModule")
        if parsed is None:
            continue
        name, object_id = parsed
        bsl = common / name / "Ext" / "Module.bsl"
        if bsl.is_file():
            try:
                rel = str(bsl.relative_to(root)).replace("\\", "/")
            except ValueError:
                rel = str(bsl)
        else:
            try:
                rel = str(xml_path.relative_to(root)).replace("\\", "/")
            except ValueError:
                rel = str(xml_path)
        out.append(
            ModuleIndexEntry(
                module_name=name,
                module_type="CommonModule",
                object_id=object_id,
                property_id=property_id,
                extension_name=extension_name,
                source_file=rel,
            )
        )
    return out


def _scan_owned_modules(
    root: Path, *, extension_name: str
) -> list[ModuleIndexEntry]:
    """Index ObjectModule / ManagerModule / RecordSetModule under type folders."""
    out: list[ModuleIndexEntry] = []
    folders = _OBJECT_MODULE_FOLDERS | _RECORD_SET_FOLDERS
    for folder_name in sorted(folders):
        base = root / folder_name
        if not base.is_dir():
            continue
        for xml_path in sorted(base.glob("*.xml")):
            md_tag = _md_tag_for_folder(folder_name)
            parsed = _parse_md_object_xml(xml_path, md_tag) if md_tag else None
            if parsed is None:
                # Fallback: any top-level child with uuid
                parsed = _parse_any_md_object_xml(xml_path)
            if parsed is None:
                continue
            name, object_id = parsed
            obj_dir = base / name
            ext_dir = obj_dir / "Ext"
            if not ext_dir.is_dir():
                continue
            for bsl_name, module_type in _OWNED_MODULE_FILES.items():
                if module_type == "ObjectModule" and folder_name in _RECORD_SET_FOLDERS:
                    continue
                if module_type == "RecordSetModule" and folder_name not in _RECORD_SET_FOLDERS:
                    # Still allow if file exists (rare)
                    pass
                bsl = ext_dir / bsl_name
                if not bsl.is_file():
                    continue
                property_id = MODULE_PROPERTY_IDS.get(module_type, "")
                if not property_id:
                    continue
                try:
                    rel = str(bsl.relative_to(root)).replace("\\", "/")
                except ValueError:
                    rel = str(bsl)
                out.append(
                    ModuleIndexEntry(
                        module_name=name,
                        module_type=module_type,
                        object_id=object_id,
                        property_id=property_id,
                        extension_name=extension_name,
                        source_file=rel,
                    )
                )
            # Forms: Catalogs/X/Forms/Y/Ext/Form/Module.bsl
            forms_dir = obj_dir / "Forms"
            if forms_dir.is_dir():
                out.extend(
                    _scan_form_modules(
                        root,
                        forms_dir,
                        parent_name=name,
                        extension_name=extension_name,
                    )
                )
    return out


def _scan_form_modules(
    root: Path,
    forms_dir: Path,
    *,
    parent_name: str,
    extension_name: str,
) -> list[ModuleIndexEntry]:
    property_id = MODULE_PROPERTY_IDS.get("FormModule", "")
    if not property_id:
        return []
    out: list[ModuleIndexEntry] = []
    for form_xml in sorted(forms_dir.glob("*.xml")):
        parsed = _parse_md_object_xml(form_xml, "Form") or _parse_any_md_object_xml(
            form_xml
        )
        if parsed is None:
            continue
        form_name, form_uuid = parsed
        bsl = forms_dir / form_name / "Ext" / "Form" / "Module.bsl"
        if not bsl.is_file():
            continue
        try:
            rel = str(bsl.relative_to(root)).replace("\\", "/")
        except ValueError:
            rel = str(bsl)
        out.append(
            ModuleIndexEntry(
                module_name=f"{parent_name}.{form_name}",
                module_type="FormModule",
                object_id=form_uuid,
                property_id=property_id,
                extension_name=extension_name,
                source_file=rel,
            )
        )
    return out


def _md_tag_for_folder(folder_name: str) -> str | None:
    for type_name, dirname in TYPE_DIRS.items():
        if dirname == folder_name:
            return type_name
    return None


def _parse_md_object_xml(xml_path: Path, tag_name: str) -> tuple[str, str] | None:
    try:
        tree = ET.parse(xml_path)
    except (OSError, ET.ParseError):
        return None
    root = tree.getroot()
    module_el = None
    for child in root:
        if _local(child.tag) == tag_name:
            module_el = child
            break
    if module_el is None:
        return None
    object_id = (module_el.get("uuid") or "").strip()
    if not object_id:
        return None
    props = _find_child(module_el, "Properties")
    name = _text(_find_child(props, "Name") if props is not None else None)
    if not name:
        name = xml_path.stem
    return name, object_id


def _parse_any_md_object_xml(xml_path: Path) -> tuple[str, str] | None:
    """Parse first MetaDataObject child that has a uuid attribute."""
    try:
        tree = ET.parse(xml_path)
    except (OSError, ET.ParseError):
        return None
    root = tree.getroot()
    for child in root:
        object_id = (child.get("uuid") or "").strip()
        if not object_id:
            continue
        props = _find_child(child, "Properties")
        name = _text(_find_child(props, "Name") if props is not None else None)
        if not name:
            name = xml_path.stem
        return name, object_id
    return None


def _scan_application_modules(
    root: Path, *, extension_name: str
) -> list[ModuleIndexEntry]:
    """Index Managed/Ordinary ApplicationModule via Configuration uuid."""
    cfg_path = root / "Configuration.xml"
    if not cfg_path.is_file():
        return []
    cfg = _parse_configuration_identity(cfg_path)
    if cfg is None:
        return []
    cfg_name, cfg_uuid = cfg
    property_id = PROPERTY_ID_APPLICATION_MODULE
    out: list[ModuleIndexEntry] = []
    mapping = (
        ("ManagedApplicationModule", "ManagedApplicationModule.bsl"),
        ("ApplicationModule", "OrdinaryApplicationModule.bsl"),
        ("ApplicationModule", "ApplicationModule.bsl"),
    )
    seen_types: set[str] = set()
    for module_type, bsl_name in mapping:
        if module_type in seen_types:
            continue
        bsl = root / "Ext" / bsl_name
        if not bsl.is_file():
            continue
        seen_types.add(module_type)
        # Prefer configuration Name; resolve() also accepts type-name aliases
        name = cfg_name or module_type
        try:
            rel = str(bsl.relative_to(root)).replace("\\", "/")
        except ValueError:
            rel = str(bsl)
        out.append(
            ModuleIndexEntry(
                module_name=name,
                module_type=module_type,
                object_id=cfg_uuid,
                property_id=property_id,
                extension_name=extension_name,
                source_file=rel,
            )
        )
    return out


def parse_metadata_object_uuid(
    xml_path: Path, *, tag_hint: str | None = None
) -> tuple[str, str] | None:
    """Return ``(name, uuid)`` from a Designer metadata XML file."""
    if tag_hint:
        parsed = _parse_md_object_xml(xml_path, tag_hint)
        if parsed is not None:
            return parsed
    if xml_path.name == "Configuration.xml":
        return _parse_md_object_xml(xml_path, "Configuration")
    folder = xml_path.parent.name
    md_tag = _md_tag_for_folder(folder)
    if md_tag:
        parsed = _parse_md_object_xml(xml_path, md_tag)
        if parsed is not None:
            return parsed
    if xml_path.parent.name == "Forms" or folder == "Forms":
        parsed = _parse_md_object_xml(xml_path, "Form")
        if parsed is not None:
            return parsed
    return _parse_any_md_object_xml(xml_path)


def normalize_bsl_source_rel(rel: Path | str) -> str | None:
    """Strip leading dirs until path looks like Designer dump-relative ``.bsl``.

    Accepts both ``CommonModules/X/Ext/Module.bsl`` and
    ``src/main/CommonModules/X/Ext/Module.bsl``.
    """
    parts = Path(str(rel).replace("\\", "/")).parts
    if not parts:
        return None
    markers = (
        "CommonModules",
        "Catalogs",
        "Documents",
        "ExchangePlans",
        "ChartsOfAccounts",
        "ChartsOfCharacteristicTypes",
        "ChartsOfCalculationTypes",
        "BusinessProcesses",
        "Tasks",
        "Reports",
        "DataProcessors",
        "InformationRegisters",
        "AccumulationRegisters",
        "AccountingRegisters",
        "CalculationRegisters",
    )
    for i, part in enumerate(parts):
        if part in markers or (part == "Ext" and i + 1 < len(parts)):
            return "/".join(parts[i:])
    return "/".join(parts) if parts[-1].endswith(".bsl") else None


def classify_bsl_relative(rel: Path) -> tuple[str, str] | None:
    """Map relative ``.bsl`` path → ``(module_type, object_xml_rel)`` or None.

    Leading project prefixes (``src/main/…``) are stripped via
    ``normalize_bsl_source_rel``.
    """
    normalized = normalize_bsl_source_rel(rel)
    if not normalized:
        return None
    parts = Path(normalized).parts
    if not parts:
        return None
    name = parts[-1]
    # Ext/ManagedApplicationModule.bsl (config root)
    if len(parts) == 2 and parts[0] == "Ext" and name in _APP_MODULE_FILES:
        return _APP_MODULE_FILES[name], "Configuration.xml"
    # TypeDir/Name/Ext/ObjectModule.bsl (optional deeper Forms handled below)
    if name in _OWNED_MODULE_FILES and len(parts) >= 4 and parts[-2] == "Ext":
        type_dir, obj_name = parts[-4], parts[-3]
        return _OWNED_MODULE_FILES[name], f"{type_dir}/{obj_name}.xml"
    if (
        name == "Module.bsl"
        and len(parts) >= 4
        and parts[-2] == "Ext"
        and "CommonModules" in parts
    ):
        idx = parts.index("CommonModules")
        if idx + 1 < len(parts):
            return "CommonModule", f"CommonModules/{parts[idx + 1]}.xml"
    # …/Forms/FormName/Ext/Form/Module.bsl
    if (
        name == "Module.bsl"
        and len(parts) >= 5
        and parts[-2] == "Form"
        and parts[-3] == "Ext"
        and "Forms" in parts
    ):
        forms_idx = parts.index("Forms")
        if forms_idx + 1 < len(parts):
            form_name = parts[forms_idx + 1]
            prefix = "/".join(parts[: forms_idx + 1])
            return "FormModule", f"{prefix}/{form_name}.xml"
    return None


def _parse_configuration_identity(cfg_path: Path) -> tuple[str, str] | None:
    try:
        tree = ET.parse(cfg_path)
    except (OSError, ET.ParseError):
        return None
    root = tree.getroot()
    conf_el = None
    for child in root:
        if _local(child.tag) == "Configuration":
            conf_el = child
            break
    if conf_el is None:
        return None
    uuid = (conf_el.get("uuid") or "").strip()
    if not uuid:
        return None
    props = _find_child(conf_el, "Properties")
    name = _text(_find_child(props, "Name") if props is not None else None)
    if not name:
        # Fallback: Name may be deeper
        name = _text(_find_desc(conf_el, "Name"))
    return name, uuid


def _type_aliases(module_type: str) -> set[str]:
    if module_type in ("ManagedApplicationModule", "ApplicationModule"):
        return {"ManagedApplicationModule", "ApplicationModule"}
    return {module_type}


def _name_matches(
    module_name: str,
    module_type: str,
    entry: ModuleIndexEntry,
) -> bool:
    if module_name == entry.module_name:
        return True
    if module_type not in ("ManagedApplicationModule", "ApplicationModule"):
        return False
    # Application module: empty name or type name → the single app module
    aliases = {
        "",
        "ManagedApplicationModule",
        "ApplicationModule",
        entry.module_name,
    }
    return module_name in aliases
