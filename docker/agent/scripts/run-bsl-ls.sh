#!/usr/bin/env sh
# Shared BSL LS MCP for the agent compose stack (sibling of Canvas).
# Listens on 0.0.0.0 so conversation containers resolve http://bsl-ls:18767/mcp.
set -eu

PORT="${BSLLS_MCP_PORT:-18767}"
JAR="${BSLLS_JAR:-/opt/bsl-ls/bsl-language-server.jar}"
URL="${BSLLS_DOWNLOAD_URL:-https://github.com/1c-syntax/bsl-language-server/releases/download/v1.1.0-rc.9/bsl-language-server-1.1.0-rc.9-exec.jar}"

mkdir -p "$(dirname "$JAR")"
if [ ! -f "$JAR" ] || [ ! -s "$JAR" ]; then
  echo "[bsl-ls] downloading jar → $JAR" >&2
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL -o "$JAR.download" "$URL"
  else
    wget -q -O "$JAR.download" "$URL"
  fi
  mv "$JAR.download" "$JAR"
fi

echo "[bsl-ls] starting on 0.0.0.0:${PORT} ($JAR)" >&2
# server.address=0.0.0.0 — reachable from other containers on the compose network.
exec java -jar "$JAR" mcp \
  --protocol streamable \
  --server.port="${PORT}" \
  --server.address=0.0.0.0
