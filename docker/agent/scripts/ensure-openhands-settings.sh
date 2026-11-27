#!/usr/bin/env sh
# Host/manual entrypoint for Settings seed (LLM + MCP).
# Compose service mounts ensure-openhands-settings.py directly.
set -eu
ROOT="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
exec python3 "$ROOT/ensure-openhands-settings.py" "$@"
