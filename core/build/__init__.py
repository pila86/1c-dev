"""Build API (ADR-008)."""

from __future__ import annotations

from core.build.result import BuildResult
from core.build.run import run_build

__all__ = ["BuildResult", "run_build"]
