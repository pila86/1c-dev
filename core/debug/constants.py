"""Diagnostics and path constants for Debug API (ADR-031 / #140)."""

from __future__ import annotations

from adapters.debug_http.constants import (
    CODE_DBGS_MISSING,
    CODE_DBGS_UNREACHABLE,
    CODE_MODULE_UNRESOLVED,
    CODE_NO_SESSION,
    CODE_NO_TARGETS,
    CODE_NOT_STOPPED,
    CODE_WAIT_TIMEOUT,
    DEFAULT_ALIAS,
    DEFAULT_AUTO_ATTACH_TYPES,
    DEFAULT_HOST,
    DEFAULT_WAIT_TIMEOUT_SEC,
    SOURCE_DEBUG,
)
from core.runtime.constants import CODE_PROJECT  # 1CR002 — project/manifest

SERVER_PID_NAME = "server.pid"
SERVER_META_NAME = "server.meta.json"
SESSION_NAME = "session.json"
NOTIFY_NAME = "server.notify"

__all__ = [
    "CODE_DBGS_MISSING",
    "CODE_DBGS_UNREACHABLE",
    "CODE_MODULE_UNRESOLVED",
    "CODE_NO_SESSION",
    "CODE_NO_TARGETS",
    "CODE_NOT_STOPPED",
    "CODE_PROJECT",
    "CODE_WAIT_TIMEOUT",
    "DEFAULT_ALIAS",
    "DEFAULT_AUTO_ATTACH_TYPES",
    "DEFAULT_HOST",
    "DEFAULT_WAIT_TIMEOUT_SEC",
    "NOTIFY_NAME",
    "SERVER_META_NAME",
    "SERVER_PID_NAME",
    "SESSION_NAME",
    "SOURCE_DEBUG",
]
