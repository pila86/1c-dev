"""XML (Designer) Source Adapter (detect / read → Metadata API, #158)."""

from __future__ import annotations

from adapters.source.xml.adapter import XmlSourceAdapter, XmlSourceError
from adapters.source.xml.constants import (
    CODE_LAYOUT_NOT_XML,
    CODE_PATH_NOT_XML_ROOT,
    CONFIGURATION_XML_NAME,
    SOURCE_FORMAT_EDT,
    SOURCE_FORMAT_XML,
)
from adapters.source.xml.detect import (
    XmlDetectResult,
    configuration_xml_path,
    detect_xml,
    is_xml_source_root,
    validate_xml_source_dir,
    xml_layout_kind,
)
from adapters.source.xml.inspect import XmlInspectInfo, inspect_xml

__all__ = [
    "CODE_LAYOUT_NOT_XML",
    "CODE_PATH_NOT_XML_ROOT",
    "CONFIGURATION_XML_NAME",
    "SOURCE_FORMAT_EDT",
    "SOURCE_FORMAT_XML",
    "XmlDetectResult",
    "XmlInspectInfo",
    "XmlSourceAdapter",
    "XmlSourceError",
    "configuration_xml_path",
    "detect_xml",
    "inspect_xml",
    "is_xml_source_root",
    "validate_xml_source_dir",
    "xml_layout_kind",
]
