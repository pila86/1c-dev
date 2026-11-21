"""XDG share paths for installed external tools (ADR-033)."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def share_root(*, env: dict[str, str] | None = None, platform: str | None = None) -> Path:
    """Root user share directory for 1c-dev (tools/, services/, data/)."""
    environ = env if env is not None else os.environ
    plat = sys.platform if platform is None else platform
    if plat == "win32":
        base = environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "1c-dev" / "share"
        return Path.home() / "AppData" / "Local" / "1c-dev" / "share"
    xdg = environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "1c-dev"
    return Path.home() / ".local" / "share" / "1c-dev"


def tools_share_dir(*, env: dict[str, str] | None = None, platform: str | None = None) -> Path:
    """Directory for installed external tool recipes."""
    return share_root(env=env, platform=platform) / "tools"


def services_share_dir(
    *, env: dict[str, str] | None = None, platform: str | None = None
) -> Path:
    """Directory for managed service state (state.json)."""
    return share_root(env=env, platform=platform) / "services"


def data_share_dir(*, env: dict[str, str] | None = None, platform: str | None = None) -> Path:
    """Directory for tool data volumes / dumps (not cache)."""
    return share_root(env=env, platform=platform) / "data"


def installed_tool_dir(
    tool_id: str,
    *,
    env: dict[str, str] | None = None,
    platform: str | None = None,
) -> Path:
    """Materialized recipe path for one tool id."""
    return tools_share_dir(env=env, platform=platform) / tool_id
