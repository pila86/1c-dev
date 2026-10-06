"""Constants for YaXUnit test adapter (ADR-029 / #122)."""

from __future__ import annotations

# Runner-extension name as shipped in YaXUnit .cfe (case-insensitive match).
RUNNER_EXTENSION_NAME = "YAXUNIT"

DEFAULT_TIMEOUT_SEC = 120.0
DEFAULT_DETAILS_LIMIT = 2000
DEFAULT_LOG_LEVEL = "debug"

REPORT_FORMAT_JUNIT = "jUnit"

# Diagnostic codes (test adapter, ADR-029)
CODE_ONECV8_MISSING = "1CT001"
CODE_IB_MISSING = "1CT002"
CODE_FILTER = "1CT003"
CODE_TIMEOUT = "1CT004"
CODE_NO_REPORT = "1CT005"
CODE_RUN_FAILED = "1CT006"
CODE_ENV = "1CT007"
CODE_CONFIG = "1CT008"
CODE_PARSE = "1CT009"
