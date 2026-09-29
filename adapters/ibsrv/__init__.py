"""Thin ibsrv adapter: daemon lifecycle + yaml helpers (ADR-025)."""

from __future__ import annotations

from adapters.ibsrv.client import (
    LOCK_PID_NAME,
    IbsrvRunResult,
    RunFn,
    build_url,
    clear_lock_pid,
    default_run,
    parse_server_config,
    read_lock_pid,
    start_daemon,
)
from adapters.ibsrv.constants import CODE_IBSRV_FAILED

__all__ = [
    "CODE_IBSRV_FAILED",
    "LOCK_PID_NAME",
    "IbsrvRunResult",
    "RunFn",
    "build_url",
    "clear_lock_pid",
    "default_run",
    "parse_server_config",
    "read_lock_pid",
    "start_daemon",
]
