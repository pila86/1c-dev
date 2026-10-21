"""Per-call debug context: resolved project target + injectable adapter dependencies.

Every ``run_*`` operation starts the same way (resolve project/config/runtime, keep
the start time, optionally restore the UI session from ``session.json``) and builds
results with the same identity fields. ``DebugContext`` holds that once, so
operations (CLI today, MCP tomorrow) only deal with their own logic.

Public ``run_*`` signatures stay unchanged; they build the context internally.
Test seams (``transport``, ``session_factory``) travel inside the context.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

from adapters.debug_http import DebugHttpError, DebugSession, TransportFn
from core.debug.common import (
    SessionFactory,
    fail_result,
    handle_adapter_error,
    load_project,
    ok_result,
    restore_session,
)
from core.debug.result import DebugResult
from core.debug.state import persist_session_runtime
from core.diagnostics import Diagnostic
from core.project.resolve import ResolvedTarget


class RestoredSession(NamedTuple):
    """UI session rebuilt from ``session.json`` plus its ``dbgs`` url / alias."""

    session: DebugSession
    url: str
    alias: str


@dataclass
class DebugContext:
    """Resolved project target for one debug operation."""

    start: Path
    started: float
    root: Path
    data: dict[str, Any]
    target: ResolvedTarget
    transport: TransportFn | None = None
    session_factory: SessionFactory | None = None

    @classmethod
    def open(
        cls,
        start: Path | None = None,
        *,
        config_id: str | None = None,
        runtime_id: str | None = None,
        transport: TransportFn | None = None,
        session_factory: SessionFactory | None = None,
        require_runtime: bool = False,
    ) -> DebugContext | DebugResult:
        """Resolve project/config/runtime; on failure return the ready ``DebugResult``."""
        started = time.perf_counter()
        start_path = (start or Path.cwd()).resolve()
        root, data, target, err = load_project(
            start_path,
            started=started,
            config_id=config_id,
            runtime_id=runtime_id,
            require_runtime=require_runtime,
        )
        if err is not None:
            return err
        assert target is not None
        return cls(
            start=start_path,
            started=started,
            root=root,
            data=data,
            target=target,
            transport=transport,
            session_factory=session_factory,
        )

    @property
    def config_id(self) -> str | None:
        return self.target.config_id

    @property
    def runtime_id(self) -> str | None:
        return self.target.runtime_id

    # --- results -----------------------------------------------------------

    def ok(self, **kwargs: Any) -> DebugResult:
        return ok_result(
            started=self.started,
            root=self.root,
            config_id=self.config_id,
            runtime_id=self.runtime_id,
            **kwargs,
        )

    def fail(self, diagnostics: list[Diagnostic], **kwargs: Any) -> DebugResult:
        return fail_result(
            started=self.started,
            root=self.root,
            config_id=self.config_id,
            runtime_id=self.runtime_id,
            diagnostics=diagnostics,
            **kwargs,
        )

    def ok_attached(self, restored: RestoredSession, **kwargs: Any) -> DebugResult:
        """``ok`` result describing a restored/attached session."""
        return self.ok(
            url=restored.url,
            alias=restored.alias,
            session_id=restored.session.session_id,
            attached=True,
            **kwargs,
        )

    def adapter_error(self, exc: DebugHttpError) -> DebugResult:
        return handle_adapter_error(
            exc, started=self.started, root=self.root, target=self.target
        )

    # --- session -----------------------------------------------------------

    def restore(
        self,
        *,
        url: str | None = None,
        start_ping: bool = False,
        ping_interval: float | None = None,
    ) -> RestoredSession | DebugResult:
        """Rebuild the UI session from disk; on failure return the failed result."""
        session, base, alias, err = restore_session(
            self.root,
            self.data,
            self.target,
            transport=self.transport,
            session_factory=self.session_factory,
            url=url,
            start_ping=start_ping,
            ping_interval=ping_interval,
        )
        if err is not None:
            err.duration = time.perf_counter() - self.started
            return err
        return RestoredSession(session, base, alias)

    def persist(self, restored: RestoredSession, **kwargs: Any) -> None:
        """Write the session runtime (targets / stop / BP) back to ``session.json``."""
        persist_session_runtime(
            self.root, restored.session, url=restored.url, alias=restored.alias, **kwargs
        )
