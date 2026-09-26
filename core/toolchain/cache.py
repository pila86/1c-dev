"""OS-specific user cache paths for toolchain jars (ADR-013)."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def cache_root(*, env: dict[str, str] | None = None, platform: str | None = None) -> Path:
    """Root user cache directory for 1c-dev (tools/, docs/, …)."""
    environ = env if env is not None else os.environ
    plat = sys.platform if platform is None else platform
    if plat == "win32":
        base = environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "1c-dev"
        return Path.home() / "AppData" / "Local" / "1c-dev"
    xdg = environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / "1c-dev"
    return Path.home() / ".cache" / "1c-dev"


def tools_cache_dir(*, env: dict[str, str] | None = None, platform: str | None = None) -> Path:
    """Directory for toolchain jars under the user cache."""
    return cache_root(env=env, platform=platform) / "tools"
