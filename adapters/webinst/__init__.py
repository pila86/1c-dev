"""Thin webinst adapter: materialize Apache publication (ADR-025 / #94).

Linux ``webinst`` binary requires root even with ``-confPath``; 1c-dev writes
``default.vrd`` + Alias/Directory itself and starts user-owned httpd from cache.
Subprocess ``publish``/``delete`` helpers remain for diagnostics / spikes.
"""

from __future__ import annotations

from adapters.webinst.client import (
    RunFn,
    WebinstError,
    WebinstRunResult,
    apply_httpd_publication,
    build_url,
    default_run,
    delete,
    file_conn_str,
    materialize_publication,
    publish,
    remove_httpd_publication,
    server_flag,
    vrd_matches_ib,
    vrd_path,
    write_default_vrd,
)
from adapters.webinst.constants import CODE_WEBINST_FAILED, CODE_WEBINST_MISSING

__all__ = [
    "CODE_WEBINST_FAILED",
    "CODE_WEBINST_MISSING",
    "WebinstError",
    "WebinstRunResult",
    "RunFn",
    "apply_httpd_publication",
    "build_url",
    "default_run",
    "delete",
    "file_conn_str",
    "materialize_publication",
    "publish",
    "remove_httpd_publication",
    "server_flag",
    "vrd_matches_ib",
    "vrd_path",
    "write_default_vrd",
]
