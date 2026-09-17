"""Discover 1C platform installs, ibcmd and 1cv8 (ADR-005)."""

from __future__ import annotations

import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

VERSION_RE = re.compile(r"(?<!\d)(\d+\.\d+\.\d+(?:\.\d+)?)(?!\d)")

_IBCMD = "ibcmd"
_ONECV8 = "1cv8"


@dataclass(frozen=True)
class ToolInfo:
    """Resolved external tool."""

    found: bool
    path: Path | None = None


@dataclass(frozen=True)
class PlatformInfo:
    """Resolved platform installation."""

    found: bool
    version: str | None = None
    path: Path | None = None


@dataclass(frozen=True)
class DiscoveryResult:
    """Full environment discovery snapshot."""

    platform: PlatformInfo
    ibcmd: ToolInfo
    onecv8: ToolInfo


def version_from_path(path: Path) -> str | None:
    """Extract platform version from a path segment (e.g. 8.3.27.1549)."""
    matches: list[str] = []
    for part in path.parts:
        m = VERSION_RE.fullmatch(part)
        if m:
            matches.append(m.group(1))
    if matches:
        return max(matches, key=_version_key)
    m = VERSION_RE.search(str(path))
    return m.group(1) if m else None


def _version_key(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in version.split("."):
        try:
            parts.append(int(piece))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def default_search_roots() -> list[Path]:
    """OS-specific platform install roots."""
    if sys.platform == "win32":
        return [
            Path(r"C:\Program Files\1cv8"),
            Path(r"C:\Program Files (x86)\1cv8"),
        ]
    return [
        Path("/opt/1cv8/x86_64"),
        Path("/opt/1C/v8.3/x86_64"),
    ]


def _tool_names(name: str) -> list[str]:
    if sys.platform == "win32":
        return [name, f"{name}.exe"]
    return [name]


def _which_tool(name: str) -> Path | None:
    for candidate in _tool_names(name):
        found = shutil.which(candidate)
        if found:
            return Path(found).resolve()
    return None


def _find_binary_in_dir(directory: Path, name: str) -> Path | None:
    for candidate in _tool_names(name):
        path = directory / candidate
        if path.is_file():
            return path.resolve()
    return None


def _iter_install_dirs(roots: list[Path]) -> list[Path]:
    """Collect versioned install directories under known roots."""
    installs: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        # Root itself may be an install (legacy /opt/1C/v8.3/x86_64).
        if _find_binary_in_dir(root, _IBCMD) or _find_binary_in_dir(root, _ONECV8):
            installs.append(root.resolve())
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            bin_dir = child / "bin" if (child / "bin").is_dir() else child
            if _find_binary_in_dir(bin_dir, _IBCMD) or _find_binary_in_dir(bin_dir, _ONECV8):
                installs.append(bin_dir.resolve())
            elif _find_binary_in_dir(child, _IBCMD) or _find_binary_in_dir(child, _ONECV8):
                installs.append(child.resolve())
    # Unique, newest first by version in path
    unique = list(dict.fromkeys(installs))
    unique.sort(key=lambda p: _version_key(version_from_path(p) or "0"), reverse=True)
    return unique


def _tool_from_installs(name: str, installs: list[Path], path_hit: Path | None) -> ToolInfo:
    if path_hit is not None:
        return ToolInfo(found=True, path=path_hit)
    for install in installs:
        found = _find_binary_in_dir(install, name)
        if found is not None:
            return ToolInfo(found=True, path=found)
    return ToolInfo(found=False, path=None)


def _platform_from(
    installs: list[Path],
    ibcmd: ToolInfo,
    onecv8: ToolInfo,
) -> PlatformInfo:
    if installs:
        best = installs[0]
        version = version_from_path(best)
        # Prefer install root (parent of bin when applicable)
        path = best.parent if best.name == "bin" else best
        return PlatformInfo(found=True, version=version, path=path)

    for tool in (ibcmd, onecv8):
        if tool.path is None:
            continue
        version = version_from_path(tool.path)
        if version is not None:
            parent = tool.path.parent
            path = parent.parent if parent.name == "bin" else parent
            return PlatformInfo(found=True, version=version, path=path)

    return PlatformInfo(found=False, version=None, path=None)


def discover_environment(
    *,
    search_roots: list[Path] | None = None,
) -> DiscoveryResult:
    """Discover platform installation and key binaries."""
    roots = search_roots if search_roots is not None else default_search_roots()
    installs = _iter_install_dirs(roots)

    ibcmd_which = _which_tool(_IBCMD)
    onecv8_which = _which_tool(_ONECV8)

    ibcmd = _tool_from_installs(_IBCMD, installs, ibcmd_which)
    onecv8 = _tool_from_installs(_ONECV8, installs, onecv8_which)
    platform = _platform_from(installs, ibcmd, onecv8)

    return DiscoveryResult(platform=platform, ibcmd=ibcmd, onecv8=onecv8)
