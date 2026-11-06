"""Discover `1cedtcli` installs (M7 spike #149; doctor wiring → #151)."""

from __future__ import annotations

import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

_EDTCLI = "1cedtcli"
_ENV_EDTCLI = "ONEC_EDTCLI"

# Directory name: 1c-edt-2026.2.2+21-x86_64
_EDT_DIR_RE = re.compile(
    r"^1c-edt-(?P<ver>\d+\.\d+\.\d+(?:\+\d+)?)(?:-|$)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class EdtCliInfo:
    """Resolved 1C:EDT CLI binary."""

    found: bool
    path: Path | None = None
    version: str | None = None


def version_from_edt_path(path: Path) -> str | None:
    """Extract EDT version from an install path segment (e.g. ``2026.2.2+21``)."""
    for part in path.parts:
        m = _EDT_DIR_RE.match(part)
        if m:
            return m.group("ver")
    m = _EDT_DIR_RE.search(str(path))
    return m.group("ver") if m else None


def _version_key(version: str) -> tuple[int, ...]:
    """Sort key; ``+build`` becomes a trailing int (``2026.2.2+21`` → (2026,2,2,21))."""
    base, _, build = version.partition("+")
    parts: list[int] = []
    for piece in base.split("."):
        try:
            parts.append(int(piece))
        except ValueError:
            parts.append(0)
    if build:
        try:
            parts.append(int(build))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def default_edt_search_roots() -> list[Path]:
    """OS-specific EDT component roots."""
    if sys.platform == "win32":
        return [
            Path(r"C:\Program Files\1C\1CE\components"),
            Path(r"C:\Program Files (x86)\1C\1CE\components"),
        ]
    return [Path("/opt/1C/1CE/components")]


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


def _iter_edt_installs(roots: list[Path]) -> list[tuple[str, Path]]:
    """Collect ``(version, 1cedtcli path)`` under known component roots."""
    found: list[tuple[str, Path]] = []
    for root in roots:
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            version = version_from_edt_path(child)
            if version is None:
                continue
            binary = _find_binary_in_dir(child, _EDTCLI)
            if binary is None:
                continue
            found.append((version, binary))
    return found


def discover_edtcli(
    *,
    env: dict[str, str] | None = None,
    search_roots: list[Path] | None = None,
) -> EdtCliInfo:
    """Resolve ``1cedtcli``: ``ONEC_EDTCLI`` → ``PATH`` → newest under search roots."""
    environ = env if env is not None else os.environ
    override = (environ.get(_ENV_EDTCLI) or "").strip()
    if override:
        path = Path(override).expanduser()
        if path.is_file():
            resolved = path.resolve()
            return EdtCliInfo(
                found=True,
                path=resolved,
                version=version_from_edt_path(resolved),
            )
        return EdtCliInfo(found=False)

    which = _which_tool(_EDTCLI)
    if which is not None:
        return EdtCliInfo(
            found=True,
            path=which,
            version=version_from_edt_path(which),
        )

    roots = search_roots if search_roots is not None else default_edt_search_roots()
    installs = _iter_edt_installs(roots)
    if not installs:
        return EdtCliInfo(found=False)

    version, path = max(installs, key=lambda item: _version_key(item[0]))
    return EdtCliInfo(found=True, path=path, version=version)
