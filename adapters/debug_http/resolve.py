"""Module objectID resolve — stub for #139 (full XML index)."""

from __future__ import annotations

from typing import Protocol

from adapters.debug_http.constants import (
    CODE_MODULE_UNRESOLVED,
    MODULE_PROPERTY_IDS,
    SOURCE_DEBUG,
)
from adapters.debug_http.errors import DebugHttpError
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
    """Placeholder until #139 builds the UUID index from XML source.

    Always raises ``1CD004`` unless an explicit override map is provided
    (useful for unit tests / known fixture UUIDs).
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
            f"модуль не резолвится (index #139): {module_type}.{module_name}"
            + (f" ext={ext}" if ext else ""),
            code=CODE_MODULE_UNRESOLVED,
            diagnostics=[
                diag_error(
                    f"objectID для {module_type}.{module_name} не найден "
                    f"(нужен module UUID index, #139)"
                    + (f"; propertyID={property_id}" if property_id else ""),
                    code=CODE_MODULE_UNRESOLVED,
                    source=SOURCE_DEBUG,
                    suggestion="передайте object_id явно или дождитесь debug.reloadMetadata (#139)",
                )
            ],
        )


def property_id_for_module_type(module_type: str) -> str:
    """Return canonical propertyID for a module kind (empty if unknown)."""
    return MODULE_PROPERTY_IDS.get(module_type, "")
