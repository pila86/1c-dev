"""Thin Apache httpd adapter: user-owned instance lifecycle (ADR-025 / #94)."""

from __future__ import annotations

from adapters.apache.client import (
    CONF_NAME,
    LOGS_DIR_NAME,
    PID_NAME,
    WWW_DIR_NAME,
    ApacheError,
    ApacheRunResult,
    RunFn,
    clear_pid,
    default_run,
    find_ws_module,
    read_pid,
    scaffold_httpd_conf,
    start_httpd,
)
from adapters.apache.constants import CODE_APACHE_FAILED

__all__ = [
    "CODE_APACHE_FAILED",
    "CONF_NAME",
    "LOGS_DIR_NAME",
    "PID_NAME",
    "WWW_DIR_NAME",
    "ApacheError",
    "ApacheRunResult",
    "RunFn",
    "clear_pid",
    "default_run",
    "find_ws_module",
    "read_pid",
    "scaffold_httpd_conf",
    "start_httpd",
]
