"""Metadata IR and API (ADR-007 create, ADR-012 read)."""

from __future__ import annotations

from core.metadata.create import create_metadata
from core.metadata.ir import (
    M2_OBJECT_TYPES,
    Attribute,
    CatalogObject,
    EnumValue,
    IrError,
    MetadataSummary,
    TabularSection,
    catalog_from_json,
    catalog_from_parts,
    load_json_input,
    parse_attr_spec,
    parse_qualified_name,
    summary_from_dict,
)
from core.metadata.read import find_metadata, get_metadata, list_metadata
from core.metadata.result import MetadataResult

__all__ = [
    "M2_OBJECT_TYPES",
    "Attribute",
    "CatalogObject",
    "EnumValue",
    "IrError",
    "MetadataResult",
    "MetadataSummary",
    "TabularSection",
    "catalog_from_json",
    "catalog_from_parts",
    "create_metadata",
    "find_metadata",
    "get_metadata",
    "list_metadata",
    "load_json_input",
    "parse_attr_spec",
    "parse_qualified_name",
    "summary_from_dict",
]
