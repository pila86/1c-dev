"""Locate platform HBK (syntax help) for docs indexing (ADR-017)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from adapters.docs.constants import HBK_FILENAME, HBK_PATH_ENV


@dataclass(frozen=True)
class HbkResolve:
    """Result of HBK path discovery."""

    found: bool
    path: Path | None = None
    source: str | None = None  # env | platform


def find_hbk(
    platform_path: Path | None = None,
    *,
    env: dict[str, str] | None = None,
) -> HbkResolve:
    """
    Resolve shcntx_ru.hbk.

    Order: ONEC_HBK_PATH → {platform}/shcntx_ru.hbk → {platform}/bin/shcntx_ru.hbk.
    """
    environ = env if env is not None else os.environ
    override = environ.get(HBK_PATH_ENV, "").strip()
    if override:
        path = Path(override).expanduser().resolve()
        if path.is_dir():
            candidate = path / HBK_FILENAME
            if candidate.is_file():
                return HbkResolve(found=True, path=candidate, source="env")
            return HbkResolve(found=False, path=candidate, source="env")
        if path.is_file():
            return HbkResolve(found=True, path=path, source="env")
        return HbkResolve(found=False, path=path, source="env")

    if platform_path is None:
        return HbkResolve(found=False)

    root = platform_path.resolve()
    candidates = [
        root / HBK_FILENAME,
        root / "bin" / HBK_FILENAME,
    ]
    # If platform.path already points at bin/
    if root.name == "bin":
        candidates.insert(0, root / HBK_FILENAME)

    for candidate in candidates:
        if candidate.is_file():
            return HbkResolve(found=True, path=candidate, source="platform")
    return HbkResolve(found=False, path=candidates[0], source="platform")
