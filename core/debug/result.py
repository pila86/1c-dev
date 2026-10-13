"""Result types for Debug API (ADR-031 / #140)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from core.debug.constants import (
    CODE_DBGS_MISSING,
    CODE_DBGS_UNREACHABLE,
    CODE_MODULE_UNRESOLVED,
    CODE_NO_SESSION,
    CODE_NO_TARGETS,
    CODE_NOT_STOPPED,
    CODE_PROJECT,
    CODE_WAIT_TIMEOUT,
)
from core.diagnostics import Diagnostic
from core.exit_codes import ENV_UNAVAILABLE, PROJECT_ERROR, RUNTIME_FAILURE, SUCCESS

Status = Literal["ok", "failed"]

_ENV_CODES = frozenset({CODE_DBGS_MISSING})
_PROJECT_CODES = frozenset({CODE_PROJECT, CODE_MODULE_UNRESOLVED})
_RUNTIME_CODES = frozenset(
    {
        CODE_DBGS_UNREACHABLE,
        CODE_NO_SESSION,
        CODE_WAIT_TIMEOUT,
        CODE_NOT_STOPPED,
        CODE_NO_TARGETS,
    }
)


@dataclass
class DebugResult:
    """Structured result for ``core.debug.*`` / ``1c-dev debug …``."""

    status: Status
    diagnostics: list[Diagnostic] = field(default_factory=list)
    duration: float | None = None
    root: Path | None = None
    config_id: str | None = None
    runtime_id: str | None = None
    # server
    host: str | None = None
    port: int | None = None
    url: str | None = None
    pid: int | None = None
    running: bool | None = None
    # session
    session_id: str | None = None
    alias: str | None = None
    attached: bool | None = None
    # targets / stop / inspection
    targets: list[dict[str, Any]] = field(default_factory=list)
    target_id: str | None = None
    module_name: str | None = None
    line_no: int | None = None
    call_stack: list[dict[str, Any]] = field(default_factory=list)
    variables: list[dict[str, Any]] = field(default_factory=list)
    eval_state: str | None = None
    expression: str | None = None
    breakpoints: list[dict[str, Any]] = field(default_factory=list)
    # meta / client hint
    modules_count: int | None = None
    client_debug_enabled: bool | None = None
    debugger_url: str | None = None
    # Suggested CLI exit (ADR-003 / ADR-031); MCP ignores.
    exit_code: int = PROJECT_ERROR

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": self.status}
        if self.duration is not None:
            payload["duration"] = round(self.duration, 3)
        if self.root is not None:
            payload["root"] = str(self.root)
        if self.config_id is not None:
            payload["configId"] = self.config_id
        if self.runtime_id is not None:
            payload["runtimeId"] = self.runtime_id
        if self.host is not None:
            payload["host"] = self.host
        if self.port is not None:
            payload["port"] = self.port
        if self.url is not None:
            payload["url"] = self.url
        if self.pid is not None:
            payload["pid"] = self.pid
        if self.running is not None:
            payload["running"] = self.running
        if self.session_id is not None:
            payload["sessionId"] = self.session_id
        if self.alias is not None:
            payload["alias"] = self.alias
        if self.attached is not None:
            payload["attached"] = self.attached
        if self.targets:
            payload["targets"] = list(self.targets)
        if self.target_id is not None:
            payload["targetId"] = self.target_id
        if self.module_name is not None:
            payload["moduleName"] = self.module_name
        if self.line_no is not None:
            payload["lineNo"] = self.line_no
        if self.call_stack:
            payload["callStack"] = list(self.call_stack)
        if self.variables:
            payload["variables"] = list(self.variables)
        if self.eval_state is not None:
            payload["evalState"] = self.eval_state
        if self.expression is not None:
            payload["expression"] = self.expression
        if self.breakpoints:
            payload["breakpoints"] = list(self.breakpoints)
        if self.modules_count is not None:
            payload["modulesCount"] = self.modules_count
        if self.client_debug_enabled is not None:
            payload["clientDebugEnabled"] = self.client_debug_enabled
        if self.debugger_url is not None:
            payload["debuggerUrl"] = self.debugger_url
        payload["exitCode"] = self.exit_code
        if self.diagnostics:
            payload["diagnostics"] = list(self.diagnostics)
        return payload


def exit_code_from_diagnostics(diagnostics: list[Diagnostic]) -> int:
    """Map ``1CD…`` / project codes → CLI exit (ADR-031 §8)."""
    codes = {d.get("code") for d in diagnostics if d.get("code")}
    if codes & _ENV_CODES:
        return ENV_UNAVAILABLE
    if codes & _RUNTIME_CODES:
        return RUNTIME_FAILURE
    if codes & _PROJECT_CODES:
        return PROJECT_ERROR
    # Ambiguous 1CD004: project if "не найден в source", else runtime — caller tags via code sets.
    if CODE_MODULE_UNRESOLVED in codes:
        return PROJECT_ERROR
    return PROJECT_ERROR


def exit_code_for_result(status: Status, diagnostics: list[Diagnostic]) -> int:
    if status == "ok" and not any(d.get("severity") == "error" for d in diagnostics):
        return SUCCESS
    return exit_code_from_diagnostics(diagnostics)
