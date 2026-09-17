"""Metadata IR and create API (ADR-007)."""

from __future__ import annotations

from core.metadata.create import create_metadata
from core.metadata.ir import (
    Attribute,
    CatalogObject,
    IrError,
    catalog_from_json,
    catalog_from_parts,
    load_json_input,
    parse_attr_spec,
    parse_qualified_name,
)
from core.metadata.result import MetadataResult

__all__ = [
    "Attribute",
    "CatalogObject",
    "IrError",
    "MetadataResult",
    "catalog_from_json",
    "catalog_from_parts",
    "create_metadata",
    "load_json_input",
    "parse_attr_spec",
    "parse_qualified_name",
]
