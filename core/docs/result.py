"""Result types for docs API (ADR-017)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from core.diagnostics import Diagnostic

Status = Literal["ok", "error"]


@dataclass
class DocsResult:
    """Structured result for docs.search / docs.get."""

    status: Status
    diagnostics: list[Diagnostic] = field(default_factory=list)
    root: Path | None = None
    platform_version: str | None = None
    index_path: Path | None = None
    index_built: bool | None = None
    hits: list[dict[str, Any]] = field(default_factory=list)
    entry: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": self.status}
        if self.root is not None:
            payload["root"] = str(self.root)
        if self.platform_version is not None:
            payload["platformVersion"] = self.platform_version
        if self.index_path is not None:
            payload["indexPath"] = str(self.index_path)
        if self.index_built is not None:
            payload["indexBuilt"] = self.index_built
        if self.hits:
            payload["hits"] = list(self.hits)
        if self.entry is not None:
            payload["entry"] = self.entry
        if self.diagnostics:
            payload["diagnostics"] = list(self.diagnostics)
        return payload
