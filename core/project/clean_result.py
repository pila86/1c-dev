"""Result types for project.clean (ADR-021)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from core.diagnostics import Diagnostic

Status = Literal["ok", "failed"]


@dataclass
class CleanResult:
    """Structured result for project.clean."""

    status: Status
    diagnostics: list[Diagnostic] = field(default_factory=list)
    duration: float | None = None
    root: Path | None = None
    source_path: Path | None = None
    runtime_dir: Path | None = None
    source_cleared: bool = False
    runtime_cleared: bool = False
    removed: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": self.status}
        if self.duration is not None:
            payload["duration"] = round(self.duration, 3)
        if self.root is not None:
            payload["root"] = str(self.root)
        if self.source_path is not None:
            payload["sourcePath"] = self._rel_or_str(self.source_path)
        if self.runtime_dir is not None:
            payload["runtimePath"] = self._rel_or_str(self.runtime_dir)
        payload["sourceCleared"] = self.source_cleared
        payload["runtimeCleared"] = self.runtime_cleared
        if self.removed:
            payload["removed"] = list(self.removed)
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
