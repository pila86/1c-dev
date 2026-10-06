"""YaXUnit adapter: ``1cv8`` RunUnitTests + jUnit → structured result (ADR-029 / #122)."""

from __future__ import annotations

from adapters.test_yaxunit.client import (
    ProcessRunResult,
    RunFn,
    YaxunitError,
    build_enterprise_run_argv,
    default_run,
    prepare_work_dir,
    run_unit_tests,
)
from adapters.test_yaxunit.config import (
    YaxunitConfigError,
    build_run_config,
    prepare_filter_extensions,
    test_case_id,
    validate_test_path,
)
from adapters.test_yaxunit.constants import (
    CODE_CONFIG,
    CODE_ENV,
    CODE_FILTER,
    CODE_IB_MISSING,
    CODE_NO_REPORT,
    CODE_ONECV8_MISSING,
    CODE_PARSE,
    CODE_RUN_FAILED,
    CODE_TIMEOUT,
    DEFAULT_DETAILS_LIMIT,
    DEFAULT_TIMEOUT_SEC,
    REPORT_FORMAT_JUNIT,
    RUNNER_EXTENSION_NAME,
)
from adapters.test_yaxunit.junit import (
    RunStatus,
    TestCaseResult,
    TestRunResult,
    TestStatus,
    YaxunitParseError,
    parse_junit,
    read_yaxunit_exit_code,
)

__all__ = [
    "CODE_CONFIG",
    "CODE_ENV",
    "CODE_FILTER",
    "CODE_IB_MISSING",
    "CODE_NO_REPORT",
    "CODE_ONECV8_MISSING",
    "CODE_PARSE",
    "CODE_RUN_FAILED",
    "CODE_TIMEOUT",
    "DEFAULT_DETAILS_LIMIT",
    "DEFAULT_TIMEOUT_SEC",
    "REPORT_FORMAT_JUNIT",
    "RUNNER_EXTENSION_NAME",
    "ProcessRunResult",
    "RunFn",
    "RunStatus",
    "TestCaseResult",
    "TestRunResult",
    "TestStatus",
    "YaxunitConfigError",
    "YaxunitError",
    "YaxunitParseError",
    "build_enterprise_run_argv",
    "build_run_config",
    "default_run",
    "parse_junit",
    "prepare_filter_extensions",
    "prepare_work_dir",
    "read_yaxunit_exit_code",
    "run_unit_tests",
    "test_case_id",
    "validate_test_path",
]
