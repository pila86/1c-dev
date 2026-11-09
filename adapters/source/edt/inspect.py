"""EDT source inspect / info (ADR-032 / #152)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from adapters.source.edt.constants import SOURCE_FORMAT_EDT
from adapters.source.edt.detect import detect_edt


@dataclass(frozen=True)
class EdtInspectInfo:
    """inspect(): format + path + EDT project name (ADR-032)."""

    format: str
    path: Path
    project_name: str | None
    is_edt: bool
    has_configuration_mdo: bool
    has_v8_nature: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "path": str(self.path),
            "projectName": self.project_name,
            "isEdt": self.is_edt,
            "hasConfigurationMdo": self.has_configuration_mdo,
            "hasV8Nature": self.has_v8_nature,
        }


def inspect_edt(path: Path) -> EdtInspectInfo:
    """Inspect candidate EDT source path."""
    detected = detect_edt(path)
    return EdtInspectInfo(
        format=SOURCE_FORMAT_EDT,
        path=detected.path,
        project_name=detected.project_name,
        is_edt=detected.is_edt,
        has_configuration_mdo=detected.has_configuration_mdo,
        has_v8_nature=detected.has_v8_nature,
    )
