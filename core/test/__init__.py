"""Test API: discover / list / run / runOne / report (ADR-029 / #123)."""

from __future__ import annotations

from core.test.constants import (
    CODE_FILTER,
    CODE_IB_MISSING,
    CODE_NO_REPORT,
    CODE_NO_SUITES,
    CODE_ONECV8_MISSING,
    CODE_PROJECT,
    CODE_RUNNER_UNSUPPORTED,
    CODE_STORE,
    CODE_SUITE_UNKNOWN,
    LAST_RESULT_REL,
    RUNNER_YAXUNIT,
    TEST_DIR_NAME,
)
from core.test.ops import (
    discover_tests,
    list_tests,
    report_tests,
    run_one_test,
    run_tests,
)
from core.test.result import TestResult, exit_code_for_run_status

__all__ = [
    "CODE_FILTER",
    "CODE_IB_MISSING",
    "CODE_NO_REPORT",
    "CODE_NO_SUITES",
    "CODE_ONECV8_MISSING",
    "CODE_PROJECT",
    "CODE_RUNNER_UNSUPPORTED",
    "CODE_STORE",
    "CODE_SUITE_UNKNOWN",
    "LAST_RESULT_REL",
    "RUNNER_YAXUNIT",
    "TEST_DIR_NAME",
    "TestResult",
    "discover_tests",
    "exit_code_for_run_status",
    "list_tests",
    "report_tests",
    "run_one_test",
    "run_tests",
]
