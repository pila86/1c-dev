"""Constants for ibcmd platform adapter (ADR-008)."""

from __future__ import annotations

IB_MARKER = "1Cv8.1CD"
DEFAULT_ARTIFACT_REL = "build/out/configuration.cf"
IBCMD_DATA_REL = ".runtime/ibcmd-data"

# Diagnostic codes (build, ADR-008)
CODE_IBCMD_MISSING = "1CB001"
CODE_PROJECT = "1CB002"
CODE_SOURCE_FORMAT = "1CB003"
CODE_SOURCE_MISSING = "1CB004"
CODE_IBCMD_FAILED = "1CB005"
CODE_ARTIFACT = "1CB006"

# Diagnostic codes (check, ADR-009)
CODE_CHECK_IBCMD_MISSING = "1CC001"
CODE_CHECK_PROJECT = "1CC002"
CODE_CHECK_IB_MISSING = "1CC003"
CODE_CHECK_FAILED = "1CC004"
