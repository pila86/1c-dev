"""1C:EDT CLI (`1cedtcli`) discovery + export (M7 / #149, #151, #155)."""

from __future__ import annotations

from .client import (
    EdtCliError,
    EdtCliRunResult,
    RunFn,
    default_run,
    export_configuration,
    is_edt_version_supported,
    prepare_export_dir,
    require_edtcli,
    version_tuple,
)
from .constants import (
    CODE_EDTCLI_COLLISION,
    CODE_EDTCLI_EMPTY_EXPORT,
    CODE_EDTCLI_FAILED,
    CODE_EDTCLI_MISSING,
    CODE_EDTCLI_VERSION,
    DEFAULT_EXPORT_TIMEOUT_SEC,
    EDTCLI_ENV,
    EDTCLI_MISSING_HINT,
    EDTCLI_SKIP_MESSAGE,
    MD_SPARROW_JDK_HINT,
    MD_SPARROW_JDK_SKIP_MESSAGE,
    MD_SPARROW_MIN_JAVA_MAJOR,
    MIN_EDT_MAJOR,
    MIN_EDT_MINOR,
    PLATFORM_SKIP_MESSAGE,
)
from .discovery import EdtCliInfo, default_edt_search_roots, discover_edtcli, version_from_edt_path

__all__ = [
    "CODE_EDTCLI_COLLISION",
    "CODE_EDTCLI_EMPTY_EXPORT",
    "CODE_EDTCLI_FAILED",
    "CODE_EDTCLI_MISSING",
    "CODE_EDTCLI_VERSION",
    "DEFAULT_EXPORT_TIMEOUT_SEC",
    "EDTCLI_ENV",
    "EDTCLI_MISSING_HINT",
    "EDTCLI_SKIP_MESSAGE",
    "EdtCliError",
    "EdtCliInfo",
    "EdtCliRunResult",
    "MD_SPARROW_JDK_HINT",
    "MD_SPARROW_JDK_SKIP_MESSAGE",
    "MD_SPARROW_MIN_JAVA_MAJOR",
    "MIN_EDT_MAJOR",
    "MIN_EDT_MINOR",
    "PLATFORM_SKIP_MESSAGE",
    "RunFn",
    "default_edt_search_roots",
    "default_run",
    "discover_edtcli",
    "export_configuration",
    "is_edt_version_supported",
    "prepare_export_dir",
    "require_edtcli",
    "version_from_edt_path",
    "version_tuple",
]
