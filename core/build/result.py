"""Result types for build API (ADR-008, PRD §23)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from core.diagnostics import Diagnostic

Status = Literal["ok", "failed"]


@dataclass
class BuildResult:
    """Structured result for 1c-dev build."""

    status: Status
    diagnostics: list[Diagnostic] = field(default_factory=list)
    duration: float | None = None
    root: Path | None = None
    runtime_path: Path | None = None
    artifact: str | None = None
    steps: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": self.status}
        if self.duration is not None:
            payload["duration"] = round(self.duration, 3)
        if self.root is not None:
            payload["root"] = str(self.root)
        if self.runtime_path is not None:
            try:
                if self.root is not None:
                    payload["runtimePath"] = self.runtime_path.relative_to(
                        self.root
                    ).as_posix()
                else:
                    payload["runtimePath"] = str(self.runtime_path)
            except ValueError:
                payload["runtimePath"] = str(self.runtime_path)
        if self.artifact is not None:
            payload["artifact"] = self.artifact
        if self.steps:
            payload["steps"] = list(self.steps)
        if self.diagnostics:
            payload["diagnostics"] = list(self.diagnostics)
        return payload
