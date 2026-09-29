"""Result type for publish.up / down / status / url (ADR-025)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from core.diagnostics import Diagnostic

Status = Literal["ok", "failed"]


@dataclass
class PublishResult:
    """Structured result for publish lifecycle operations."""

    status: Status
    diagnostics: list[Diagnostic] = field(default_factory=list)
    duration: float | None = None
    root: Path | None = None
    profile_id: str | None = None
    backend: str | None = None
    runtime_path: Path | None = None
    config_path: Path | None = None
    data_path: Path | None = None
    running: bool = False
    pid: int | None = None
    url: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "running": self.running,
        }
        if self.duration is not None:
            payload["duration"] = round(self.duration, 3)
        if self.root is not None:
            payload["root"] = str(self.root)
        if self.profile_id is not None:
            payload["profile"] = self.profile_id
        if self.backend is not None:
            payload["backend"] = self.backend
        if self.runtime_path is not None:
            payload["runtimePath"] = self._rel_or_str(self.runtime_path)
        if self.config_path is not None:
            payload["configPath"] = self._rel_or_str(self.config_path)
        if self.data_path is not None:
            payload["dataPath"] = self._rel_or_str(self.data_path)
        if self.pid is not None:
            payload["pid"] = self.pid
        if self.url is not None:
            payload["url"] = self.url
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
