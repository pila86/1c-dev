"""Project manifest: detect, load, validate, init, ide configure (ADR-004, ADR-006, ADR-016)."""

from __future__ import annotations

from .constants import MANIFEST_NAME
from .detect import detect_manifest, detect_project
from .ide import configure_ide
from .init import init_project
from .load import load_manifest
from .result import ProjectResult
from .validate import validate_manifest, validate_project

__all__ = [
    "MANIFEST_NAME",
    "ProjectResult",
    "configure_ide",
    "detect_manifest",
    "detect_project",
    "init_project",
    "load_manifest",
    "validate_manifest",
    "validate_project",
]
