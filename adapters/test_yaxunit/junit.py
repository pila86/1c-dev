"""Parse YaXUnit jUnit XML into structured test results (ADR-029)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from adapters.test_yaxunit.config import test_case_id
from adapters.test_yaxunit.constants import CODE_PARSE, DEFAULT_DETAILS_LIMIT

TestStatus = Literal["passed", "failed", "error", "skipped"]
RunStatus = Literal["passed", "failed", "error", "empty"]

_CHILD_STATUS: dict[str, TestStatus] = {
    "failure": "failed",
    "error": "error",
    "skipped": "skipped",
}


class YaxunitParseError(ValueError):
    """jUnit XML could not be parsed."""

    def __init__(self, message: str, *, code: str = CODE_PARSE) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass(frozen=True)
class TestCaseResult:
    """One testcase from a YaXUnit jUnit report."""

    name: str
    test: str
    module: str
    extension: str | None
    test_set: str | None
    context: str | None
    status: TestStatus
    duration_sec: float
    message: str = ""
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TestRunResult:
    """Structured result of a YaXUnit run (jUnit + process metadata)."""

    status: RunStatus
    passed: int
    failed: int
    error: int
    skipped: int
    total: int
    duration_sec: float
    tests: tuple[TestCaseResult, ...]
    report_path: Path | None = None
    process_exit_code: int | None = None
    yaxunit_exit_code: int | None = None
    timed_out: bool = False
    properties: tuple[tuple[str, str], ...] = ()
    argv: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "passed": self.passed,
            "failed": self.failed,
            "error": self.error,
            "skipped": self.skipped,
            "total": self.total,
            "durationSec": self.duration_sec,
            "tests": [t.to_dict() for t in self.tests],
            "reportPath": str(self.report_path) if self.report_path else None,
            "processExitCode": self.process_exit_code,
            "yaxunitExitCode": self.yaxunit_exit_code,
            "timedOut": self.timed_out,
            "properties": dict(self.properties),
            "argv": list(self.argv),
        }


def _parse_float(raw: str | None) -> float:
    if raw is None or raw == "":
        return 0.0
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _truncate(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n…[truncated]"


def _case_status(case: ET.Element) -> tuple[TestStatus, str, str]:
    for child in case:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        status = _CHILD_STATUS.get(tag)
        if status is None:
            continue
        message = child.get("message") or ""
        details = (child.text or "").strip()
        return status, message, details
    return "passed", "", ""


def _suite_test_set(name: str | None, context: str | None) -> str | None:
    if not name:
        return None
    if context:
        suffix = f" [{context}]"
        if name.endswith(suffix):
            return name[: -len(suffix)] or name
    return name


def parse_junit(
    path: Path,
    *,
    details_limit: int = DEFAULT_DETAILS_LIMIT,
) -> TestRunResult:
    """
    Map YaXUnit jUnit XML → ``TestRunResult``.

    Mapping (ADR-029): ``package``→extension, ``classname``→module,
    ``name``/``context``→testSet+context, ``testcase@name``→test,
    child tags → status.
    """
    if not path.is_file():
        raise YaxunitParseError(f"jUnit-отчёт не найден: {path}")
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise YaxunitParseError(f"некорректный jUnit XML: {exc}") from exc

    root_tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    if root_tag not in {"testsuites", "testsuite"}:
        raise YaxunitParseError(f"ожидался корень <testsuites>, получено <{root_tag}>")

    properties: list[tuple[str, str]] = []
    for prop in root.findall("properties/property"):
        pname = prop.get("name")
        if pname is not None:
            properties.append((pname, prop.get("value") or ""))

    cases: list[TestCaseResult] = []
    suites = root.iter("testsuite") if root_tag == "testsuites" else [root]
    for suite in suites:
        extension = suite.get("package")
        module = suite.get("classname") or ""
        context = suite.get("context")
        test_set = _suite_test_set(suite.get("name"), context)
        for case in suite.findall("testcase"):
            test_name = case.get("name") or ""
            case_module = module or (case.get("classname") or "").split(".", 1)[0]
            case_context = case.get("context") or context
            status, message, details = _case_status(case)
            cases.append(
                TestCaseResult(
                    name=test_case_id(
                        module=case_module,
                        test=test_name,
                        context=case_context,
                    ),
                    test=test_name,
                    module=case_module,
                    extension=extension,
                    test_set=test_set,
                    context=case_context,
                    status=status,
                    duration_sec=_parse_float(case.get("time")),
                    message=message,
                    details=_truncate(details, details_limit),
                )
            )

    passed = sum(1 for c in cases if c.status == "passed")
    failed = sum(1 for c in cases if c.status == "failed")
    error = sum(1 for c in cases if c.status == "error")
    skipped = sum(1 for c in cases if c.status == "skipped")
    total = len(cases)
    duration = sum(c.duration_sec for c in cases)

    if total == 0:
        run_status: RunStatus = "empty"
    elif failed or error:
        run_status = "failed"
    else:
        run_status = "passed"

    return TestRunResult(
        status=run_status,
        passed=passed,
        failed=failed,
        error=error,
        skipped=skipped,
        total=total,
        duration_sec=duration,
        tests=tuple(cases),
        report_path=path.resolve(),
        properties=tuple(properties),
    )


def read_yaxunit_exit_code(path: Path) -> int | None:
    """Read YaXUnit ``exitCode`` file (UTF-8 with BOM); ``0``/``1``."""
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8-sig").strip()
    except OSError:
        return None
    if not text:
        return None
    try:
        return int(text.split()[0])
    except ValueError:
        return None
