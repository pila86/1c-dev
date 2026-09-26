"""Diagnostics model (PRD §36, ADR-003)."""

from __future__ import annotations

from typing import Literal, TypedDict

Severity = Literal["error", "warning", "info", "hint"]


class Diagnostic(TypedDict, total=False):
    """Единый объект диагностики. Обязательны severity и message."""

    severity: Severity
    code: str
    message: str
    file: str
    object: str
    module: str
    line: int
    column: int
    source: str
    documentationLink: str
    relatedObject: str
    suggestion: str
    fix: str


def error(
    message: str,
    *,
    code: str | None = None,
    file: str | None = None,
    source: str = "runtime",
    suggestion: str | None = None,
) -> Diagnostic:
    """Создать diagnostic с severity=error."""
    diag: Diagnostic = {
        "severity": "error",
        "message": message,
        "source": source,
    }
    if code is not None:
        diag["code"] = code
    if file is not None:
        diag["file"] = file
    if suggestion is not None:
        diag["suggestion"] = suggestion
    return diag


def warning(
    message: str,
    *,
    code: str | None = None,
    file: str | None = None,
    source: str = "runtime",
    suggestion: str | None = None,
) -> Diagnostic:
    """Создать diagnostic с severity=warning."""
    diag: Diagnostic = {
        "severity": "warning",
        "message": message,
        "source": source,
    }
    if code is not None:
        diag["code"] = code
    if file is not None:
        diag["file"] = file
    if suggestion is not None:
        diag["suggestion"] = suggestion
    return diag


def info(
    message: str,
    *,
    code: str | None = None,
    file: str | None = None,
    source: str = "runtime",
    suggestion: str | None = None,
) -> Diagnostic:
    """Создать diagnostic с severity=info."""
    diag: Diagnostic = {
        "severity": "info",
        "message": message,
        "source": source,
    }
    if code is not None:
        diag["code"] = code
    if file is not None:
        diag["file"] = file
    if suggestion is not None:
        diag["suggestion"] = suggestion
    return diag
