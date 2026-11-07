"""XML source inspect / info (PRD §50 / #158)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from adapters.source.xml.constants import SOURCE_FORMAT_XML
from adapters.source.xml.detect import detect_xml


@dataclass(frozen=True)
class XmlInspectInfo:
    """inspect(): format + path для Designer XML."""

    format: str
    path: Path
    is_xml: bool
    has_configuration_xml: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "path": str(self.path),
            "isXml": self.is_xml,
            "hasConfigurationXml": self.has_configuration_xml,
        }


def inspect_xml(path: Path) -> XmlInspectInfo:
    """Inspect candidate Designer XML source path."""
    detected = detect_xml(path)
    return XmlInspectInfo(
        format=SOURCE_FORMAT_XML,
        path=detected.path,
        is_xml=detected.is_xml,
        has_configuration_xml=detected.has_configuration_xml,
    )
