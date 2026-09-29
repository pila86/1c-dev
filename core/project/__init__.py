"""Project manifest API: detect, validate, init, ide, clean, list."""

from __future__ import annotations

from .clean import run_clean
from .clean_result import CleanResult
from .constants import HOME_MANIFEST_REL, MANIFEST_NAME
from .detect import detect_manifest, detect_project, list_projects
from .ide import configure_ide
from .init import init_project
from .load import load_manifest
from .resolve import ResolvedTarget, resolve_config_runtime
from .result import ProjectResult
from .validate import validate_manifest, validate_project

__all__ = [
    "HOME_MANIFEST_REL",
    "MANIFEST_NAME",
    "CleanResult",
    "ProjectResult",
    "ResolvedTarget",
    "configure_ide",
    "detect_manifest",
    "detect_project",
    "init_project",
    "list_projects",
    "load_manifest",
    "resolve_config_runtime",
    "run_clean",
    "validate_manifest",
    "validate_project",
]
