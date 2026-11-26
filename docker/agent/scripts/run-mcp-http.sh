#!/usr/bin/env bash
# Run 1c-dev MCP over Streamable HTTP for Agent Canvas.
# Canvas Test connection and conversations reach this via host network.
set -euo pipefail

export PATH="/opt/1c-dev-venv/bin:/usr/local/bin:${PATH}"
HOST="${MCP_HTTP_HOST:-0.0.0.0}"
PORT="${MCP_HTTP_PORT:-9100}"
WORKSPACE="${AGENT_WORKSPACE:-/workspace}"

cd "$WORKSPACE"
printf '[mcp-1c-dev] streamable-http on http://%s:%s/mcp (cwd=%s)\n' "$HOST" "$PORT" "$PWD"

exec python - <<'PY'
import os
from mcp.server.fastmcp import FastMCP
from mcp_server.tools import register_tools

host = os.environ.get("MCP_HTTP_HOST", "127.0.0.1")
port = int(os.environ.get("MCP_HTTP_PORT", "9100"))
server = FastMCP("1c-dev", host=host, port=port)
register_tools(server)
server.run(transport="streamable-http")
PY
