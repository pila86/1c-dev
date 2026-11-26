#!/usr/bin/env bash
# First-run: install catalog tools + start process services (bsl-ls by default).
# Compose tools (v8std/bsl-search) need Docker — skipped unless docker CLI works.
set -u
# Do not set -e: individual tools may fail without aborting agent start.

log() { printf '[tools-bootstrap] %s\n' "$*" >&2; }

if [[ "${SKIP_TOOLS_BOOTSTRAP:-0}" == "1" ]]; then
  log "SKIP_TOOLS_BOOTSTRAP=1"
  exit 0
fi

if ! command -v 1c-dev >/dev/null 2>&1; then
  log "1c-dev not on PATH — skip"
  exit 0
fi

# HuggingFace under share (conversation often mounts only ~/.cache/1c-dev, not ~/.cache).
SHARE_ROOT="${XDG_DATA_HOME:-${HOME:-/tmp}/.local/share}/1c-dev"
export HF_HOME="${HF_HOME:-$SHARE_ROOT/hf-cache}"
export HUGGINGFACE_HUB_CACHE="${HUGGINGFACE_HUB_CACHE:-$HF_HOME}"
mkdir -p "$HF_HOME" 2>/dev/null || true

MARKER="$SHARE_ROOT/.bootstrap-done"
if [[ -f "$MARKER" && "${TOOLS_BOOTSTRAP_FORCE:-0}" != "1" ]]; then
  log "already bootstrapped ($MARKER)"
  # Still ensure requested services are up (idempotent).
else
  log "1c-dev tools install --all"
  if 1c-dev tools install --all; then
    mkdir -p "$(dirname "$MARKER")" 2>/dev/null || true
    date -u +%Y-%m-%dT%H:%M:%SZ >"$MARKER" 2>/dev/null || true
  else
    log "tools install --all reported errors (continuing)"
  fi
fi

# Default: process adapter only (no DinD). Override: TOOLS_BOOTSTRAP_SERVICES=bsl-ls,v8std
SERVICES="${TOOLS_BOOTSTRAP_SERVICES:-bsl-ls}"
IFS=',' read -r -a svc_list <<EOF
$SERVICES
EOF
for svc in "${svc_list[@]}"; do
  svc="$(printf '%s' "$svc" | tr -d '[:space:]')"
  [[ -n "$svc" ]] || continue
  log "1c-dev services up $svc"
  1c-dev services up "$svc" || log "services up $svc failed (continuing)"
done

exit 0
