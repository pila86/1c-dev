"""Module objectID resolve: stub + XML source index (#139 / #145)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

from adapters.debug_http.constants import (
    CODE_MODULE_UNRESOLVED,
    MODULE_PROPERTY_IDS,
    SOURCE_DEBUG,
)
from adapters.debug_http.errors import DebugHttpError
from adapters.debug_http.index import (
    ModulesIndex,
    SourceRoot,
    classify_bsl_relative,
    load_or_build_index,
    modules_cache_path,
    reload_metadata,
    source_roots_from_configuration,
)
from adapters.debug_http.models import ModuleRef
from core.diagnostics import error as diag_error


class ObjectIdResolver(Protocol):
    """Resolve ``moduleName`` + ``moduleType`` (+ optional extension) → object/property IDs."""

    def resolve(
        self,
        module_name: str,
        module_type: str,
        *,
        extension_name: str | None = None,
    ) -> ModuleRef:
        """Return ``ModuleRef`` or raise ``DebugHttpError`` with ``1CD004``."""
        ...


class StubObjectIdResolver:
    """Test/placeholder resolver with optional override map.

    Always raises ``1CD004`` unless an explicit override map is provided.
    """

    def __init__(self, overrides: dict[tuple[str, str, str], ModuleRef] | None = None) -> None:
        # key: (module_name, module_type, extension_name or "")
        self._overrides = overrides or {}

    def resolve(
        self,
        module_name: str,
        module_type: str,
        *,
        extension_name: str | None = None,
    ) -> ModuleRef:
        ext = extension_name or ""
        key = (module_name, module_type, ext)
        if key in self._overrides:
            return self._overrides[key]
        property_id = MODULE_PROPERTY_IDS.get(module_type, "")
        raise DebugHttpError(
            f"модуль не резолвится: {module_type}.{module_name}"
            + (f" ext={ext}" if ext else ""),
            code=CODE_MODULE_UNRESOLVED,
            diagnostics=[
                diag_error(
                    f"objectID для {module_type}.{module_name} не найден "
                    f"(stub resolver; нужен XmlObjectIdResolver / reloadMetadata)"
                    + (f"; propertyID={property_id}" if property_id else ""),
                    code=CODE_MODULE_UNRESOLVED,
                    source=SOURCE_DEBUG,
                    suggestion=(
                        "передайте object_id явно или используйте XmlObjectIdResolver "
                        "из XML source (#139)"
                    ),
                )
            ],
        )


class XmlObjectIdResolver:
    """Resolve objectID from XML source index (main conf + extensions).

    For extension modules ``extension_name`` is required (empty → main only).
    """

    def __init__(self, index: ModulesIndex) -> None:
        self._index = index

    @property
    def index(self) -> ModulesIndex:
        return self._index

    @classmethod
    def from_roots(
        cls,
        scope_root: Path,
        roots: Sequence[SourceRoot],
        *,
        cache_path: Path | None = None,
        force: bool = False,
    ) -> XmlObjectIdResolver:
        """Build/load index for the given source roots and return a resolver."""
        index = load_or_build_index(
            scope_root, roots, cache_path=cache_path, force=force
        )
        return cls(index)

    @classmethod
    def from_configuration(
        cls,
        scope_root: Path,
        configuration: dict[str, Any],
        *,
        cache_path: Path | None = None,
        force: bool = False,
    ) -> XmlObjectIdResolver:
        """Convenience: roots from a ``configurations[]`` manifest entry."""
        roots = source_roots_from_configuration(scope_root, configuration)
        return cls.from_roots(
            scope_root, roots, cache_path=cache_path, force=force
        )

    def reload(
        self,
        scope_root: Path,
        roots: Sequence[SourceRoot],
        *,
        cache_path: Path | None = None,
    ) -> ModulesIndex:
        """Rebuild cache (adapter helper for ``debug.reloadMetadata``)."""
        self._index = reload_metadata(scope_root, roots, cache_path=cache_path)
        return self._index

    def resolve(
        self,
        module_name: str,
        module_type: str,
        *,
        extension_name: str | None = None,
    ) -> ModuleRef:
        ext = extension_name or ""
        # empty extensionName → main configuration only;
        # extensions always require explicit extensionName (ADR-031 / #139)
        matches = self._index.find(
            module_name, module_type, extension_name=ext
        )

        if not matches:
            if not ext:
                only_ext = self._index.find(
                    module_name, module_type, any_extension=True
                )
                if only_ext:
                    names = sorted({e.extension_name for e in only_ext})
                    raise DebugHttpError(
                        f"модуль только в расширении — нужен extensionName: "
                        f"{module_type}.{module_name}",
                        code=CODE_MODULE_UNRESOLVED,
                        diagnostics=[
                            diag_error(
                                f"{module_type}.{module_name} найден в: "
                                f"{', '.join(names)}",
                                code=CODE_MODULE_UNRESOLVED,
                                source=SOURCE_DEBUG,
                                suggestion="передайте extensionName",
                            )
                        ],
                    )
            property_id = MODULE_PROPERTY_IDS.get(module_type, "")
            raise DebugHttpError(
                f"модуль не резолвится: {module_type}.{module_name}"
                + (f" ext={ext}" if ext else ""),
                code=CODE_MODULE_UNRESOLVED,
                diagnostics=[
                    diag_error(
                        f"objectID для {module_type}.{module_name} не найден в XML index"
                        + (f"; propertyID={property_id}" if property_id else ""),
                        code=CODE_MODULE_UNRESOLVED,
                        source=SOURCE_DEBUG,
                        suggestion=(
                            "проверьте source.path / extensionName или вызовите "
                            "reloadMetadata"
                        ),
                    )
                ],
            )

        if len(matches) > 1:
            raise DebugHttpError(
                f"несколько objectID для {module_type}.{module_name}"
                + (f" ext={ext}" if ext else ""),
                code=CODE_MODULE_UNRESOLVED,
                diagnostics=[
                    diag_error(
                        "неоднозначный index hit: "
                        + ", ".join(m.object_id for m in matches),
                        code=CODE_MODULE_UNRESOLVED,
                        source=SOURCE_DEBUG,
                        suggestion="уточните moduleType / extensionName",
                    )
                ],
            )

        hit = matches[0]
        return ModuleRef(
            object_id=hit.object_id,
            property_id=hit.property_id,
            module_name=hit.module_name,
            module_type=hit.module_type,
            extension_name=hit.extension_name,
        )

    def resolve_from_file(
        self,
        bsl_path: Path | str,
        *,
        extension_name: str | None = None,
        search_roots: Sequence[SourceRoot] | None = None,
    ) -> ModuleRef:
        """Resolve ``.bsl`` path → objectID/propertyID via index (#145).

        Accepts:
        - absolute path to ``.bsl``;
        - path relative to cwd / project (``src/main/CommonModules/…/Module.bsl``);
        - path relative to ``source.path`` (``CommonModules/…/Module.bsl``,
          ``Catalogs/X/Ext/ObjectModule.bsl``).
        """
        from adapters.debug_http.index import normalize_bsl_source_rel

        path = Path(bsl_path)
        ext = extension_name or ""
        roots_meta = self._index.roots
        candidates: list[tuple[str, str]] = []  # (rel, extensionName)

        def _add_rel(rel: str, root_ext: str) -> None:
            if ext and root_ext != ext:
                return
            candidates.append((rel.replace("\\", "/"), root_ext))
            normalized = normalize_bsl_source_rel(rel)
            if normalized and normalized != rel.replace("\\", "/"):
                candidates.append((normalized, root_ext))

        def _add_abs_file(resolved: Path) -> None:
            for meta in roots_meta:
                if not isinstance(meta, dict):
                    continue
                root_s = str(meta.get("path") or "")
                if not root_s:
                    continue
                root = Path(root_s).resolve()
                try:
                    rel = str(resolved.relative_to(root)).replace("\\", "/")
                except ValueError:
                    continue
                _add_rel(rel, str(meta.get("extensionName") or ""))
            if search_roots:
                for src in search_roots:
                    try:
                        rel = str(resolved.relative_to(src.path.resolve())).replace(
                            "\\", "/"
                        )
                    except ValueError:
                        continue
                    _add_rel(rel, src.extension_name)

        # Absolute file
        if path.is_absolute() and path.is_file():
            _add_abs_file(path.resolve())
        else:
            raw = str(path).replace("\\", "/")
            # cwd / project-relative file (src/main/…)
            cwd_file = (Path.cwd() / path).resolve()
            if cwd_file.is_file():
                _add_abs_file(cwd_file)
            # under each indexed source root
            for meta in roots_meta:
                if not isinstance(meta, dict):
                    continue
                root_s = str(meta.get("path") or "")
                if not root_s:
                    continue
                root = Path(root_s)
                root_ext = str(meta.get("extensionName") or "")
                under = (root / path).resolve()
                if under.is_file():
                    _add_abs_file(under)
                # strip leading dirs until dump-relative suffix exists under root
                parts = Path(raw).parts
                for i in range(len(parts)):
                    suffix = "/".join(parts[i:])
                    candidate = (root / suffix).resolve()
                    if candidate.is_file():
                        _add_abs_file(candidate)
                    _add_rel(suffix, root_ext)
            # plain source-relative string (even if file not checked yet)
            if ext:
                _add_rel(raw, ext)
            else:
                _add_rel(raw, "")
                for meta in roots_meta:
                    if not isinstance(meta, dict):
                        continue
                    root_ext = str(meta.get("extensionName") or "")
                    if root_ext:
                        _add_rel(raw, root_ext)

        # Deduplicate preserving order
        seen: set[tuple[str, str]] = set()
        uniq: list[tuple[str, str]] = []
        for item in candidates:
            if item in seen:
                continue
            seen.add(item)
            uniq.append(item)

        matches = []
        for rel, cand_ext in uniq:
            hits = self._index.find_by_source_file(rel, extension_name=cand_ext)
            matches.extend(hits)

        if not matches and uniq:
            # Path may not be indexed yet — parse layout and read object xml
            for rel, cand_ext in uniq:
                rebuilt = self._resolve_path_via_layout(rel, extension_name=cand_ext)
                if rebuilt is not None:
                    return rebuilt

        if not matches:
            raise DebugHttpError(
                f"модуль не резолвится по пути: {bsl_path}",
                code=CODE_MODULE_UNRESOLVED,
                diagnostics=[
                    diag_error(
                        f"objectID для .bsl не найден: {bsl_path}",
                        code=CODE_MODULE_UNRESOLVED,
                        source=SOURCE_DEBUG,
                        suggestion=(
                            "проверьте путь относительно source.path "
                            "(например Catalogs/X/Ext/ObjectModule.bsl) "
                            "или от корня проекта (src/main/…); "
                            "вызовите reloadMetadata"
                        ),
                    )
                ],
            )

        # Prefer main configuration when extension_name not specified
        if not ext:
            main_hits = [m for m in matches if not m.extension_name]
            if main_hits:
                matches = main_hits
            elif len({m.extension_name for m in matches}) > 1:
                names = sorted({m.extension_name for m in matches})
                raise DebugHttpError(
                    f"модуль только в расширении — нужен extensionName: {bsl_path}",
                    code=CODE_MODULE_UNRESOLVED,
                    diagnostics=[
                        diag_error(
                            f"путь найден в: {', '.join(names)}",
                            code=CODE_MODULE_UNRESOLVED,
                            source=SOURCE_DEBUG,
                            suggestion="передайте extensionName",
                        )
                    ],
                )

        if len(matches) > 1:
            # Same object across roots — ok if identical ids
            ids = {(m.object_id, m.property_id, m.extension_name) for m in matches}
            if len(ids) > 1:
                raise DebugHttpError(
                    f"несколько objectID для пути {bsl_path}",
                    code=CODE_MODULE_UNRESOLVED,
                    diagnostics=[
                        diag_error(
                            "неоднозначный index hit: "
                            + ", ".join(m.object_id for m in matches),
                            code=CODE_MODULE_UNRESOLVED,
                            source=SOURCE_DEBUG,
                            suggestion="уточните --extension",
                        )
                    ],
                )

        hit = matches[0]
        return ModuleRef(
            object_id=hit.object_id,
            property_id=hit.property_id,
            module_name=hit.module_name,
            module_type=hit.module_type,
            extension_name=hit.extension_name,
        )

    def _resolve_path_via_layout(
        self,
        rel: str,
        *,
        extension_name: str,
    ) -> ModuleRef | None:
        from adapters.debug_http.index import (
            normalize_bsl_source_rel,
            parse_metadata_object_uuid,
        )

        normalized = normalize_bsl_source_rel(rel) or rel
        classified = classify_bsl_relative(Path(normalized))
        if classified is None:
            return None
        module_type, xml_rel = classified
        property_id = MODULE_PROPERTY_IDS.get(module_type, "")
        if not property_id:
            return None
        for meta in self._index.roots:
            if not isinstance(meta, dict):
                continue
            root_ext = str(meta.get("extensionName") or "")
            if root_ext != extension_name:
                continue
            root_s = str(meta.get("path") or "")
            if not root_s:
                continue
            xml_path = Path(root_s) / xml_rel
            if not xml_path.is_file():
                continue
            parsed = parse_metadata_object_uuid(xml_path)
            if parsed is None:
                continue
            name, object_id = parsed
            return ModuleRef(
                object_id=object_id,
                property_id=property_id,
                module_name=name,
                module_type=module_type,
                extension_name=extension_name,
            )
        return None


def resolve_explicit_ids(
    object_id: str,
    property_id: str,
    *,
    module_name: str = "",
    module_type: str = "",
    extension_name: str = "",
) -> ModuleRef:
    """Low-level escape: trust caller-provided objectID/propertyID (#145)."""
    oid = object_id.strip()
    pid = property_id.strip()
    if not oid or not pid:
        raise DebugHttpError(
            "нужны --object-id и --property-id",
            code=CODE_MODULE_UNRESOLVED,
            diagnostics=[
                diag_error(
                    "пустой objectID или propertyID",
                    code=CODE_MODULE_UNRESOLVED,
                    source=SOURCE_DEBUG,
                    suggestion="передайте оба идентификатора или используйте --file/--module",
                )
            ],
        )
    return ModuleRef(
        object_id=oid,
        property_id=pid,
        module_name=module_name,
        module_type=module_type,
        extension_name=extension_name,
    )


def property_id_for_module_type(module_type: str) -> str:
    """Return canonical propertyID for a module kind (empty if unknown)."""
    return MODULE_PROPERTY_IDS.get(module_type, "")


def default_cache_path(scope_root: Path) -> Path:
    """``<scope>/.1c-dev/debug/modules-cache.json``."""
    return modules_cache_path(scope_root)
