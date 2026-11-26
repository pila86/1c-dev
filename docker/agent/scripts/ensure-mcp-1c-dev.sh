#!/usr/bin/env sh
# Compatibility wrapper → ensure-mcp-servers.sh
exec /bin/sh "$(dirname "$0")/ensure-mcp-servers.sh" "$@"
