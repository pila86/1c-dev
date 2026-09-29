"""Paths for publish artifacts under .1c-dev/publish/ (ADR-022 / ADR-025)."""

from __future__ import annotations

from pathlib import Path

from core.project.constants import HOME_PUBLISH_DIR_NAME

DEFAULT_HTTP_PORT = 8314
DEFAULT_WEBINST_PORT = 8315
DEFAULT_HTTP_ADDRESS = "localhost"
DEFAULT_HTTP_BASE = "/"
DEFAULT_WEBINST_ADDRESS = "127.0.0.1"
YAML_NAME = "ibsrv.yaml"
DATA_DIR_NAME = "data"
HTTPD_CONF_NAME = "httpd.conf"
WWW_DIR_NAME = "www"


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


def default_httpd_conf_path(project_root: Path, profile_id: str) -> Path:
    """Default user-owned httpd.conf for webinst backend."""
    return profile_dir(project_root, profile_id) / HTTPD_CONF_NAME


def default_www_dir(project_root: Path, profile_id: str) -> Path:
    """Default publication www directory for webinst."""
    return profile_dir(project_root, profile_id) / WWW_DIR_NAME


def resolve_config_path(
    project_root: Path,
    profile_id: str,
    config_rel: str | None,
) -> Path:
    """Resolve yaml path from profile.config or default layout."""
    if config_rel:
        return (project_root / config_rel).resolve()
    return default_config_path(project_root, profile_id).resolve()


def resolve_www_dir(
    project_root: Path,
    profile_id: str,
    dir_rel: str | None,
) -> Path:
    """Resolve webinst ``-dir`` from profile.dir or default layout."""
    if dir_rel:
        return (project_root / dir_rel).resolve()
    return default_www_dir(project_root, profile_id).resolve()


def resolve_httpd_conf_path(
    project_root: Path,
    profile_id: str,
    confpath_rel: str | None,
) -> Path:
    """Resolve webinst ``-confPath`` from profile.confpath or default."""
    if confpath_rel:
        return (project_root / confpath_rel).resolve()
    return default_httpd_conf_path(project_root, profile_id).resolve()
