"""Project manifest: detect, load, validate, init (ADR-004, ADR-006)."""

from __future__ import annotations

from .constants import MANIFEST_NAME
from .detect import detect_manifest, detect_project
from .init import init_project
from .load import load_manifest
from .result import ProjectResult
from .validate import validate_manifest, validate_project

__all__ = [
    "MANIFEST_NAME",
    "ProjectResult",
    "detect_manifest",
    "detect_project",
    "init_project",
    "load_manifest",
    "validate_manifest",
    "validate_project",
]
