"""Constants for ibcmd platform adapter (ADR-008)."""

from __future__ import annotations

IB_MARKER = "1Cv8.1CD"
DEFAULT_ARTIFACT_REL = "build/out/configuration.cf"
IBCMD_DATA_REL = ".runtime/ibcmd-data"

# Diagnostic codes
CODE_IBCMD_MISSING = "1CB001"
CODE_PROJECT = "1CB002"
CODE_SOURCE_FORMAT = "1CB003"
CODE_SOURCE_MISSING = "1CB004"
CODE_IBCMD_FAILED = "1CB005"
CODE_ARTIFACT = "1CB006"
