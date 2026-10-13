"""Module objectID resolve: stub + XML source index (#139)."""

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


def property_id_for_module_type(module_type: str) -> str:
    """Return canonical propertyID for a module kind (empty if unknown)."""
    return MODULE_PROPERTY_IDS.get(module_type, "")


def default_cache_path(scope_root: Path) -> Path:
    """``<scope>/.1c-dev/debug/modules-cache.json``."""
    return modules_cache_path(scope_root)
