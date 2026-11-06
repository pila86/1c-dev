"""1C:EDT CLI (`1cedtcli`) discovery helpers (M7 / #149)."""

from __future__ import annotations

from .discovery import EdtCliInfo, default_edt_search_roots, discover_edtcli, version_from_edt_path

__all__ = [
    "EdtCliInfo",
    "default_edt_search_roots",
    "discover_edtcli",
    "version_from_edt_path",
]
