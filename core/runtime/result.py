"""Result type for runtime.start / stop / status (ADR-019)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from core.diagnostics import Diagnostic

Status = Literal["ok", "failed"]


@dataclass
class RuntimeResult:
    """Structured result for runtime client lifecycle operations."""

    status: Status
    diagnostics: list[Diagnostic] = field(default_factory=list)
    duration: float | None = None
    root: Path | None = None
    runtime_path: Path | None = None
    running: bool = False
    pid: int | None = None
    mode: str | None = None
    client: str | None = None
    debug_enabled: bool = False
    debugger_url: str | None = None

    def to_payload(self) -> dict[str, Any]:
        debug: dict[str, Any] = {"enabled": self.debug_enabled}
        if self.debugger_url:
            debug["debuggerUrl"] = self.debugger_url
        payload: dict[str, Any] = {
            "status": self.status,
            "running": self.running,
            "debug": debug,
        }
        if self.duration is not None:
            payload["duration"] = round(self.duration, 3)
        if self.root is not None:
            payload["root"] = str(self.root)
        if self.runtime_path is not None:
            payload["runtimePath"] = self._rel_or_str(self.runtime_path)
        if self.pid is not None:
            payload["pid"] = self.pid
        if self.mode is not None:
            payload["mode"] = self.mode
        if self.client is not None:
            payload["client"] = self.client
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
