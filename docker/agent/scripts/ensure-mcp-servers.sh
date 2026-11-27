#!/usr/bin/env sh
# Seed OpenHands Agent Canvas MCP settings (idempotent).
#
# - 1c-dev: stdio inside conversation sandbox (platform + /workspace)
# - bsl-ls / v8std / bsl-search: HTTP siblings on compose network; conversation
#   joins via docker-wrapper --network. URLs use compose DNS names.
#
# Canvas UI "Test connection" may stay red (Canvas is host-networked and does
# not resolve bsl-ls / cannot exec 1c-dev). New conversations matter.
set -eu

OH_API_BASE="${OH_API_BASE:-http://127.0.0.1:3000}"
WAIT_SECS="${WAIT_SECS:-180}"
SLEEP_SECS="${SLEEP_SECS:-2}"
TMPDIR="${TMPDIR:-/tmp}"
SETTINGS_FILE="${TMPDIR}/oh-settings.$$.json"
RESP_FILE="${TMPDIR}/oh-mcp-resp.$$.json"

# 127.0.0.1 + published ports: Canvas Test (host net, NO_PROXY) works.
# Conversation: same URL via mcp-local-forward.py → compose DNS (bsl-ls / v8std-mcp / mcp-atlassian).
BSL_LS_URL="${MCP_BSL_LS_URL:-http://127.0.0.1:18767/mcp}"
V8STD_URL="${MCP_V8STD_URL:-http://127.0.0.1:18766/mcp}"
BSL_SEARCH_URL="${MCP_BSL_SEARCH_URL:-http://127.0.0.1:18005/mcp}"
ATLASSIAN_URL="${MCP_ATLASSIAN_URL:-http://127.0.0.1:18768/mcp}"

# Comma-separated extras to seed besides 1c-dev. Default: bsl-ls,v8std,atlassian
# Set MCP_HTTP_SERVERS=bsl-ls or empty to limit; bsl-search behind profile.
MCP_HTTP_SERVERS="${MCP_HTTP_SERVERS:-bsl-ls,v8std,atlassian}"

log() { printf '[ensure-mcp] %s\n' "$*"; }

cleanup() {
  rm -f "$SETTINGS_FILE" "$RESP_FILE" 2>/dev/null || true
}
trap cleanup EXIT

curl_api() {
  out="$1"
  method="$2"
  path="$3"
  shift 3
  if [ -n "${LOCAL_BACKEND_API_KEY:-}" ]; then
    curl -sS -o "$out" -w '%{http_code}' \
      -X "$method" "${OH_API_BASE}${path}" \
      -H 'Content-Type: application/json' \
      -H 'Accept: application/json' \
      -H "X-Session-API-Key: ${LOCAL_BACKEND_API_KEY}" \
      "$@"
  else
    curl -sS -o "$out" -w '%{http_code}' \
      -X "$method" "${OH_API_BASE}${path}" \
      -H 'Content-Type: application/json' \
      -H 'Accept: application/json' \
      "$@"
  fi
}

wait_ready() {
  i=0
  code=000
  while [ "$i" -lt "$WAIT_SECS" ]; do
    code="$(curl_api "$SETTINGS_FILE" GET /api/settings || printf '000')"
    if [ "$code" = "200" ]; then
      log "Canvas API ready (${OH_API_BASE})"
      return 0
    fi
    i=$((i + SLEEP_SECS))
    sleep "$SLEEP_SECS"
  done
  log "ERROR: Canvas API not ready after ${WAIT_SECS}s (last HTTP ${code})"
  return 1
}

# Return 0 if key exists with expected marker substring in settings JSON.
mcp_has() {
  key="$1"
  marker="$2"
  [ -f "$SETTINGS_FILE" ] || return 1
  grep -q "\"${key}\"" "$SETTINGS_FILE" || return 1
  # crude but enough for idempotent seed (no jq in curl image by default)
  grep -A30 "\"${key}\"" "$SETTINGS_FILE" | grep -q "$marker" || return 1
  if grep -A30 "\"${key}\"" "$SETTINGS_FILE" | grep -q '"enabled"[[:space:]]*:[[:space:]]*false'; then
    return 1
  fi
  return 0
}

upsert_mcp() {
  key="$1"
  body="$2"
  marker="$3"

  curl_api "$SETTINGS_FILE" GET /api/settings >/dev/null || true
  if mcp_has "$key" "$marker"; then
    log "MCP '${key}' already ok — skip"
    return 0
  fi

  if grep -q "\"${key}\"" "$SETTINGS_FILE" 2>/dev/null; then
    log "Replacing MCP '${key}'"
    curl_api "$RESP_FILE" DELETE "/api/settings/mcp/${key}" >/dev/null || true
  fi

  log "Creating MCP '${key}'"
  resp_code="$(curl_api "$RESP_FILE" POST "/api/settings/mcp/${key}" -d "$body" || printf '000')"
  if [ "$resp_code" = "201" ] || [ "$resp_code" = "200" ]; then
    log "MCP '${key}' created (HTTP ${resp_code})"
    return 0
  fi

  log "Create HTTP ${resp_code}; trying PATCH merge"
  # Escape body for embedding — body is compact JSON object.
  patch=$(printf '{"agent_settings_diff":{"mcp_config":{"%s":%s}}}' "$key" "$body")
  # body already has enabled? add via wrap
  patch_code="$(curl_api "$RESP_FILE" PATCH /api/settings -d "$patch" || printf '000')"
  if [ "$patch_code" != "200" ]; then
    log "ERROR: upsert '${key}' failed HTTP ${patch_code}"
    head -c 500 "$RESP_FILE" 2>/dev/null || true
    echo
    return 1
  fi
  log "MCP '${key}' upserted via PATCH"
  return 0
}

wait_ready

# --- 1c-dev stdio (conversation) ---
upsert_mcp "1c-dev" \
  '{"transport":"stdio","command":"1c-dev","args":["mcp"],"description":"1c-dev toolchain MCP (stdio inside conversation /workspace)","enabled":true}' \
  '"command"[[:space:]]*:[[:space:]]*"1c-dev"'

# --- HTTP siblings (compose DNS) ---
seed_http() {
  name="$1"
  case "$name" in
    bsl-ls|bsl-language-server)
      upsert_mcp "bsl-language-server" \
        "$(printf '{"transport":"streamable-http","url":"%s","description":"BSL LS (sibling compose service bsl-ls)","enabled":true}' "$BSL_LS_URL")" \
        "$BSL_LS_URL"
      ;;
    v8std)
      upsert_mcp "v8std" \
        "$(printf '{"transport":"streamable-http","url":"%s","description":"v8std MCP (sibling compose)","enabled":true}' "$V8STD_URL")" \
        "$V8STD_URL"
      ;;
    bsl-search)
      upsert_mcp "bsl-search" \
        "$(printf '{"transport":"streamable-http","url":"%s","description":"bsl-search MCP (sibling compose, profile mcp-search)","enabled":true}' "$BSL_SEARCH_URL")" \
        "$BSL_SEARCH_URL"
      ;;
    atlassian|mcp-atlassian)
      # Replaces UI-added STDIO `uvx mcp-atlassian` (broken in conversation sandbox).
      upsert_mcp "mcp-atlassian" \
        "$(printf '{"transport":"streamable-http","url":"%s","description":"Jira/Confluence MCP (sibling compose mcp-atlassian)","enabled":true}' "$ATLASSIAN_URL")" \
        "$ATLASSIAN_URL"
      ;;
    "" ) ;;
    *)
      log "WARN: unknown MCP_HTTP_SERVERS entry '${name}' — skip"
      ;;
  esac
}

OLD_IFS=$IFS
IFS=','
for item in $MCP_HTTP_SERVERS; do
  IFS=$OLD_IFS
  # trim spaces
  item=$(printf '%s' "$item" | tr -d '[:space:]')
  seed_http "$item"
  IFS=','
done
IFS=$OLD_IFS

curl_api "$SETTINGS_FILE" GET /api/settings >/dev/null || true
log "OK: seeded MCP servers (stdio 1c-dev + HTTP: ${MCP_HTTP_SERVERS})"
log "NOTE: conversation needs compose network (docker-wrapper); use a NEW chat"
exit 0
