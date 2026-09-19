"""Map ibcmd stdout/stderr to Diagnostics (ADR-008, PRD §52)."""

from __future__ import annotations

from adapters.platform_ibcmd.constants import CODE_IBCMD_FAILED
from core.diagnostics import Diagnostic, error

_MAX_DETAIL = 800


def diagnostics_from_output(
    *,
    step: str,
    returncode: int,
    stdout: str,
    stderr: str,
) -> list[Diagnostic]:
    """Build diagnostics for a failed (or noisy) ibcmd invocation."""
    detail = (stderr or stdout or "").strip()
    if len(detail) > _MAX_DETAIL:
        detail = detail[:_MAX_DETAIL] + "…"
    message = f"ibcmd {step} завершился с кодом {returncode}"
    if detail:
        message = f"{message}: {detail}"
    return [
        error(
            message,
            code=CODE_IBCMD_FAILED,
            source="platform",
        )
    ]
