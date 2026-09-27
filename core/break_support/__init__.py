"""Break support API: strip ParentConfigurations* (ADR-020, #74)."""

from __future__ import annotations

from core.break_support.result import BreakSupportResult
from core.break_support.run import run_break_support
from core.break_support.strip import collect_support_artifacts, strip_parent_configurations

__all__ = [
    "BreakSupportResult",
    "collect_support_artifacts",
    "run_break_support",
    "strip_parent_configurations",
]
