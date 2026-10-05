"""Constants for Test API orchestration (ADR-029 / #123)."""

from __future__ import annotations

from core.project.constants import HOME_DIR_NAME

# Artifact layout under project home
TEST_DIR_NAME = f"{HOME_DIR_NAME}/test"
LAST_RESULT_NAME = "last-result.json"
LAST_RESULT_REL = f"{TEST_DIR_NAME}/{LAST_RESULT_NAME}"
WORK_DIR_NAME = "work"
WORK_DIR_REL = f"{TEST_DIR_NAME}/{WORK_DIR_NAME}"

RUNNER_YAXUNIT = "yaxunit"
RUNNER_VANESSA = "vanessa"
SUPPORTED_RUNNERS = frozenset({RUNNER_YAXUNIT})

# Diagnostic codes (core/test orchestration; adapter uses 1CT001–1CT009)
CODE_PROJECT = "1CT101"
CODE_NO_SUITES = "1CT102"
CODE_SUITE_UNKNOWN = "1CT103"
CODE_RUNNER_UNSUPPORTED = "1CT104"
CODE_NO_REPORT = "1CT105"
CODE_FILTER = "1CT106"
CODE_ONECV8_MISSING = "1CT107"
CODE_IB_MISSING = "1CT108"
CODE_STORE = "1CT109"
# Runner ensure (ADR-029 §7a)
CODE_RUNNER_CFE_MISSING = "1CT110"
CODE_RUNNER_ENSURE_FAILED = "1CT111"
CODE_IBCMD_MISSING = "1CT112"
CODE_TEST_EXT_MISSING = "1CT113"

RUNNER_STATE_NAME = "runner-yaxunit.json"
