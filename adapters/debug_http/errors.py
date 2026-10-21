"""Exceptions for HTTP Debug Protocol adapter."""

from __future__ import annotations

from adapters.debug_http.constants import CODE_DBGS_UNREACHABLE, SOURCE_DEBUG
from core.diagnostics import Diagnostic
from core.diagnostics import error as diag_error


class DebugHttpError(Exception):
    """Debug HTTP adapter failure with structured diagnostics."""

    def __init__(
        self,
        message: str,
        *,
        code: str = CODE_DBGS_UNREACHABLE,
        diagnostics: list[Diagnostic] | None = None,
        timeout: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        #: HTTP read timeout (long-poll ping returns 204 after ~5 s; not a failure).
        self.timeout = timeout
        self.diagnostics = diagnostics or [
            diag_error(message, code=code, source=SOURCE_DEBUG)
        ]
