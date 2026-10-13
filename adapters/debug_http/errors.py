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
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.diagnostics = diagnostics or [
            diag_error(message, code=code, source=SOURCE_DEBUG)
        ]
