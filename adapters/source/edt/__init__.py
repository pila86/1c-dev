"""EDT Source Adapter (detect / read → Metadata API, ADR-032 / #152)."""

from __future__ import annotations

from adapters.source.edt.adapter import EdtSourceAdapter, EdtSourceError
from adapters.source.edt.constants import (
    CODE_LAYOUT_NOT_EDT,
    CODE_PATH_NOT_EDT_ROOT,
    CONFIGURATION_MDO_REL,
    PROJECT_FILE_NAME,
    SOURCE_FORMAT_EDT,
    SOURCE_FORMAT_XML,
    V8_CONFIGURATION_NATURE,
)
from adapters.source.edt.detect import (
    EdtDetectResult,
    configuration_mdo_path,
    detect_edt,
    edt_layout_kind,
    has_v8_configuration_nature,
    is_edt_project_root,
    read_edt_project_name,
    validate_edt_source_dir,
)
from adapters.source.edt.inspect import EdtInspectInfo, inspect_edt

__all__ = [
    "CODE_LAYOUT_NOT_EDT",
    "CODE_PATH_NOT_EDT_ROOT",
    "CONFIGURATION_MDO_REL",
    "PROJECT_FILE_NAME",
    "SOURCE_FORMAT_EDT",
    "SOURCE_FORMAT_XML",
    "V8_CONFIGURATION_NATURE",
    "EdtDetectResult",
    "EdtInspectInfo",
    "EdtSourceAdapter",
    "EdtSourceError",
    "configuration_mdo_path",
    "detect_edt",
    "edt_layout_kind",
    "has_v8_configuration_nature",
    "inspect_edt",
    "is_edt_project_root",
    "read_edt_project_name",
    "validate_edt_source_dir",
]
