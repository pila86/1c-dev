"""Constants for 1cv8 client adapter (ADR-019)."""

from __future__ import annotations

CLIENT_PID_REL = ".runtime/client.pid"
CLIENT_META_REL = ".runtime/client.meta.json"
MODE_ENTERPRISE = "enterprise"

# Diagnostic codes (runtime client lifecycle, ADR-019)
CODE_ONECV8_MISSING = "1CR001"
CODE_PROJECT = "1CR002"
CODE_IB_MISSING = "1CR003"
CODE_CLIENT_FAILED = "1CR004"
