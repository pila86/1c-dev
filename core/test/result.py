"""Result types for Test API (ADR-029, PRD §26)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from core.diagnostics import Diagnostic
from core.exit_codes import (
    CHECK_FAILURE,
    ENV_UNAVAILABLE,
    PROJECT_ERROR,
    RUNTIME_FAILURE,
    SUCCESS,
    TEST_FAILURE,
)
from core.test.constants import (
    CODE_FILTER,
    CODE_IB_MISSING,
    CODE_IBCMD_MISSING,
    CODE_NO_REPORT,
    CODE_NO_SUITES,
    CODE_ONECV8_MISSING,
    CODE_PROJECT,
    CODE_RUNNER_CFE_MISSING,
    CODE_RUNNER_ENSURE_FAILED,
    CODE_RUNNER_UNSUPPORTED,
    CODE_STORE,
    CODE_SUITE_UNKNOWN,
)

# ok — discover/list/report without test-run verdict; rest — run/runOne (ADR-029).
Status = Literal["ok", "passed", "failed", "error", "empty"]

_ENV_CODES = frozenset(
    {CODE_ONECV8_MISSING, CODE_RUNNER_CFE_MISSING, CODE_IBCMD_MISSING, "1CT001", "1CT007"}
)
_PROJECT_CODES = frozenset(
    {
        CODE_PROJECT,
        CODE_NO_SUITES,
        CODE_SUITE_UNKNOWN,
        CODE_RUNNER_UNSUPPORTED,
        CODE_FILTER,
        CODE_IB_MISSING,
        CODE_NO_REPORT,
        CODE_STORE,
        "1CT002",
        "1CT003",
        "1CT008",
    }
)
_RUNTIME_CODES = frozenset(
    {CODE_RUNNER_ENSURE_FAILED, "1CT004", "1CT005", "1CT006", "1CT009"}
)


@dataclass
class TestResult:
    """Structured result for test.discover / list / run / runOne / report."""

    status: Status
    diagnostics: list[Diagnostic] = field(default_factory=list)
    duration: float | None = None
    root: Path | None = None
    runtime_path: Path | None = None
    config_id: str | None = None
    runtime_id: str | None = None
    suite_ids: list[str] = field(default_factory=list)
    # discover
    suites: list[dict[str, Any]] = field(default_factory=list)
    modules: list[dict[str, Any]] = field(default_factory=list)
    # list / run / report (PRD §26)
    passed: int | None = None
    failed: int | None = None
    error: int | None = None
    skipped: int | None = None
    total: int | None = None
    duration_sec: float | None = None
    tests: list[dict[str, Any]] = field(default_factory=list)
    report_path: str | None = None
    # list provenance: "report" | "discover"
    source: str | None = None
    incomplete: bool = False
    # Runner preflight (YAXUNIT from cache + safe-mode), ADR-029 §7a.
    runner_ensure: dict[str, Any] | None = None
    # Suggested CLI exit (ADR-003 / ADR-029); MCP ignores.
    exit_code: int = PROJECT_ERROR

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": self.status}
        if self.duration is not None:
            payload["duration"] = round(self.duration, 3)
        if self.root is not None:
            payload["root"] = str(self.root)
        if self.runtime_path is not None:
            payload["runtimePath"] = self._rel_or_str(self.runtime_path)
        if self.config_id is not None:
            payload["configId"] = self.config_id
        if self.runtime_id is not None:
            payload["runtimeId"] = self.runtime_id
        if self.suite_ids:
            payload["suiteIds"] = list(self.suite_ids)
        if self.suites:
            payload["suites"] = list(self.suites)
        if self.modules:
            payload["modules"] = list(self.modules)
        if self.passed is not None:
            payload["passed"] = self.passed
        if self.failed is not None:
            payload["failed"] = self.failed
        if self.error is not None:
            payload["error"] = self.error
        if self.skipped is not None:
            payload["skipped"] = self.skipped
        if self.total is not None:
            payload["total"] = self.total
        if self.duration_sec is not None:
            payload["durationSec"] = round(self.duration_sec, 3)
        if self.tests:
            payload["tests"] = list(self.tests)
        if self.report_path is not None:
            payload["reportPath"] = self.report_path
        if self.source is not None:
            payload["source"] = self.source
        if self.incomplete:
            payload["incomplete"] = True
        if self.runner_ensure is not None:
            payload["runnerEnsure"] = dict(self.runner_ensure)
        payload["exitCode"] = self.exit_code
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


def exit_code_for_run_status(
    status: Status,
    *,
    total: int,
    diagnostics: list[Diagnostic] | None = None,
) -> int:
    """Map run verdict / diagnostics → CLI exit (ADR-029 §8)."""
    if diagnostics:
        codes = {d.get("code") for d in diagnostics if d.get("code")}
        if codes & _ENV_CODES:
            return ENV_UNAVAILABLE
        if codes & _PROJECT_CODES:
            return PROJECT_ERROR
        if codes & _RUNTIME_CODES:
            return RUNTIME_FAILURE
    if status == "passed" and total > 0:
        return SUCCESS
    if status in {"failed", "error"}:
        return TEST_FAILURE
    if status == "empty" or total == 0:
        return CHECK_FAILURE
    if status == "ok":
        return SUCCESS
    return RUNTIME_FAILURE


def exit_code_from_diagnostics(diagnostics: list[Diagnostic]) -> int:
    """Exit code for orchestration failures (no test verdict)."""
    codes = {d.get("code") for d in diagnostics if d.get("code")}
    if codes & _ENV_CODES:
        return ENV_UNAVAILABLE
    if codes & _RUNTIME_CODES:
        return RUNTIME_FAILURE
    return PROJECT_ERROR
