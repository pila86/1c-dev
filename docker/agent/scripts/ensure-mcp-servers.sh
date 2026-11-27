#!/usr/bin/env sh
# Compatibility wrapper → ensure-openhands-settings.py (LLM + MCP seed).
set -eu
ROOT="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
exec python3 "$ROOT/ensure-openhands-settings.py" "$@"
