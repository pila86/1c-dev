"""1C:EDT CLI (`1cedtcli`) discovery helpers (M7 / #149, doctor #151)."""

from __future__ import annotations

from .constants import (
    EDTCLI_ENV,
    EDTCLI_MISSING_HINT,
    EDTCLI_SKIP_MESSAGE,
    MD_SPARROW_JDK_HINT,
    MD_SPARROW_JDK_SKIP_MESSAGE,
    MD_SPARROW_MIN_JAVA_MAJOR,
)
from .discovery import EdtCliInfo, default_edt_search_roots, discover_edtcli, version_from_edt_path

__all__ = [
    "EDTCLI_ENV",
    "EDTCLI_MISSING_HINT",
    "EDTCLI_SKIP_MESSAGE",
    "EdtCliInfo",
    "MD_SPARROW_JDK_HINT",
    "MD_SPARROW_JDK_SKIP_MESSAGE",
    "MD_SPARROW_MIN_JAVA_MAJOR",
    "default_edt_search_roots",
    "discover_edtcli",
    "version_from_edt_path",
]
