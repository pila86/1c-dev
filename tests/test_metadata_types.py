"""Coverage catalog foundation (ADR-018 / #60)."""

from __future__ import annotations

from adapters.source.xmlgen.constants import XMLGEN_COMMIT
from core.metadata.types import (
    CREATE_OBJECT_TYPES,
    M2_OBJECT_TYPES,
    META_DSL_OBJECT_TYPES,
    TYPE_DIRS,
    UPDATE_OBJECT_TYPES,
    WRITE_OBJECT_TYPES,
)


def test_meta_dsl_has_exactly_23_types() -> None:
    assert len(META_DSL_OBJECT_TYPES) == 23
    assert "Subsystem" not in META_DSL_OBJECT_TYPES


def test_write_catalog_is_meta_plus_subsystem() -> None:
    assert WRITE_OBJECT_TYPES == META_DSL_OBJECT_TYPES | frozenset({"Subsystem"})
    assert len(WRITE_OBJECT_TYPES) == 24
    assert CREATE_OBJECT_TYPES is WRITE_OBJECT_TYPES
    assert UPDATE_OBJECT_TYPES is WRITE_OBJECT_TYPES
    assert M2_OBJECT_TYPES is WRITE_OBJECT_TYPES


def test_type_dirs_cover_write_catalog() -> None:
    assert set(TYPE_DIRS) == WRITE_OBJECT_TYPES
    assert TYPE_DIRS["Subsystem"] == "Subsystems"
    assert TYPE_DIRS["DefinedType"] == "DefinedTypes"
    assert TYPE_DIRS["HTTPService"] == "HTTPServices"
    assert TYPE_DIRS["ChartOfAccounts"] == "ChartsOfAccounts"


def test_xmlgen_pin_documented_for_coverage() -> None:
    # Pin verified to include MetaWriter SUPPORTED_TYPES (23) + subsystem CLI.
    assert XMLGEN_COMMIT == "19f67bfed6d15f051f9568678bab1701b7735f95"
    assert len(XMLGEN_COMMIT) == 40
