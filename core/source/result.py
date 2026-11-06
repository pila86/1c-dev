"""Result types for source.convert (ADR-032 / #156)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from core.diagnostics import Diagnostic

Status = Literal["ok", "failed"]


@dataclass
class ConvertResult:
    """Structured result for ``source.convert``."""

    status: Status
    diagnostics: list[Diagnostic] = field(default_factory=list)
    duration: float | None = None
    root: Path | None = None
    config_id: str | None = None
    source_path: Path | None = None
    from_format: str | None = None
    to_format: str | None = None
    source_rel: str | None = None
    steps: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": self.status}
        if self.duration is not None:
            payload["duration"] = round(self.duration, 3)
        if self.root is not None:
            payload["root"] = str(self.root)
        if self.config_id is not None:
            payload["configId"] = self.config_id
        if self.from_format is not None:
            payload["fromFormat"] = self.from_format
        if self.to_format is not None:
            payload["toFormat"] = self.to_format
        if self.source_rel is not None:
            payload["sourcePath"] = self.source_rel
        elif self.source_path is not None:
            payload["sourcePath"] = self._rel_or_str(self.source_path)
        if self.steps:
            payload["steps"] = list(self.steps)
        if self.diagnostics:
            payload["diagnostics"] = list(self.diagnostics)
        return payload

    def _rel_or_str(self, path: Path) -> str:
        try:
            if self.root is not None:
                return path.relative_to(self.root).as_posix()
        except ValueError:
            pass
        return str(path)
