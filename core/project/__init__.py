"""Project manifest: detect, load, validate, init, ide configure, clean (ADR-004/006/016/021)."""

from __future__ import annotations

from .clean import run_clean
from .clean_result import CleanResult
from .constants import MANIFEST_NAME
from .detect import detect_manifest, detect_project
from .ide import configure_ide
from .init import init_project
from .load import load_manifest
from .result import ProjectResult
from .validate import validate_manifest, validate_project

__all__ = [
    "MANIFEST_NAME",
    "CleanResult",
    "ProjectResult",
    "configure_ide",
    "detect_manifest",
    "detect_project",
    "init_project",
    "load_manifest",
    "run_clean",
    "validate_manifest",
    "validate_project",
]
