"""Paths for publish artifacts under .1c-dev/publish/ (ADR-022 / ADR-025)."""

from __future__ import annotations

from pathlib import Path

from core.project.constants import HOME_PUBLISH_DIR_NAME

DEFAULT_HTTP_PORT = 8314
DEFAULT_HTTP_ADDRESS = "localhost"
DEFAULT_HTTP_BASE = "/"
YAML_NAME = "ibsrv.yaml"
DATA_DIR_NAME = "data"


def publish_root(project_root: Path) -> Path:
    """``.1c-dev/publish`` under project scope root."""
    return project_root / HOME_PUBLISH_DIR_NAME


def profile_dir(project_root: Path, profile_id: str) -> Path:
    """``.1c-dev/publish/<profile>``."""
    return publish_root(project_root) / profile_id


def default_config_path(project_root: Path, profile_id: str) -> Path:
    """Default ibsrv YAML path for a profile."""
    return profile_dir(project_root, profile_id) / YAML_NAME


def data_dir(project_root: Path, profile_id: str) -> Path:
    """ibsrv ``--data`` directory for a profile."""
    return profile_dir(project_root, profile_id) / DATA_DIR_NAME


def resolve_config_path(
    project_root: Path,
    profile_id: str,
    config_rel: str | None,
) -> Path:
    """Resolve yaml path from profile.config or default layout."""
    if config_rel:
        return (project_root / config_rel).resolve()
    return default_config_path(project_root, profile_id).resolve()
