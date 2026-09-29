"""Discover platform configuration template roots (tmplts / ADR-024 / #91)."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TemplateRootsResult:
    """Resolved tmplts roots from 1cestart.cfg + OS defaults."""

    roots: list[Path]
    """Existing directories (unique, order: cfg locations then defaults)."""

    configured: list[Path]
    """All configured paths (may include missing dirs)."""

    cfg_paths: list[Path]
    """1cestart.cfg files that were read."""


def default_tmplts_roots() -> list[Path]:
    """OS-specific default tmplts directories (ADR-024)."""
    home = Path.home()
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "").strip()
        if appdata:
            return [Path(appdata) / "1C" / "1cv8" / "tmplts"]
        return [home / "AppData" / "Roaming" / "1C" / "1cv8" / "tmplts"]
    # Linux / macOS
    return [home / ".1cv8" / "1C" / "1cv8" / "tmplts"]


def onecestart_cfg_candidates() -> list[Path]:
    """Candidate paths for 1cestart.cfg (Linux / Windows)."""
    home = Path.home()
    if sys.platform == "win32":
        candidates: list[Path] = []
        appdata = os.environ.get("APPDATA", "").strip()
        if appdata:
            candidates.append(Path(appdata) / "1C" / "1cestart" / "1cestart.cfg")
        all_users = os.environ.get("ALLUSERSPROFILE", "").strip() or os.environ.get(
            "ProgramData", ""
        ).strip()
        if all_users:
            candidates.append(Path(all_users) / "1C" / "1cestart" / "1cestart.cfg")
        if not candidates:
            candidates.append(
                home / "AppData" / "Roaming" / "1C" / "1cestart" / "1cestart.cfg"
            )
        return candidates
    return [home / ".1C" / "1cestart" / "1cestart.cfg"]


def parse_configuration_templates_locations(text: str) -> list[Path]:
    """
    Extract ConfigurationTemplatesLocation values from 1cestart.cfg content.

    Supports repeated keys and semicolon/comma-separated multi-values.
    """
    locations: list[Path] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("\ufeff"):
            line = line.lstrip("\ufeff").strip()
        key, sep, value = line.partition("=")
        if sep != "=":
            continue
        if key.strip().casefold() != "configurationtemplateslocation":
            continue
        for part in value.replace(",", ";").split(";"):
            cleaned = part.strip().strip('"').strip("'")
            if cleaned:
                locations.append(Path(cleaned).expanduser())
    return locations


def read_templates_locations_from_cfg(cfg_path: Path) -> list[Path]:
    """Read ConfigurationTemplatesLocation from one 1cestart.cfg (empty if unreadable)."""
    try:
        text = cfg_path.read_text(encoding="utf-8-sig")
    except OSError:
        return []
    return parse_configuration_templates_locations(text)


def discover_template_roots(
    *,
    cfg_paths: list[Path] | None = None,
    default_roots: list[Path] | None = None,
    include_missing: bool = False,
) -> TemplateRootsResult:
    """
    Resolve tmplts roots: ConfigurationTemplatesLocation from 1cestart.cfg + defaults.

    Existing directories are returned in ``roots``. Configured paths (including missing)
    are in ``configured`` when collected from cfg/defaults.
    """
    cfgs = cfg_paths if cfg_paths is not None else onecestart_cfg_candidates()
    defaults = default_roots if default_roots is not None else default_tmplts_roots()

    configured: list[Path] = []
    read_cfgs: list[Path] = []
    for cfg in cfgs:
        if not cfg.is_file():
            continue
        read_cfgs.append(cfg.resolve())
        for loc in read_templates_locations_from_cfg(cfg):
            resolved = loc.expanduser()
            try:
                resolved = resolved.resolve()
            except OSError:
                pass
            if resolved not in configured:
                configured.append(resolved)

    for root in defaults:
        resolved = root.expanduser()
        try:
            resolved = resolved.resolve()
        except OSError:
            pass
        if resolved not in configured:
            configured.append(resolved)

    roots = [p for p in configured if p.is_dir()]
    if include_missing:
        return TemplateRootsResult(roots=roots, configured=configured, cfg_paths=read_cfgs)
    return TemplateRootsResult(roots=roots, configured=configured, cfg_paths=read_cfgs)
