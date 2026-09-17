"""Environment doctor: discovery report and capability gaps (ADR-005)."""

from __future__ import annotations

from .result import DoctorResult
from .run import run_doctor

__all__ = [
    "DoctorResult",
    "run_doctor",
]
