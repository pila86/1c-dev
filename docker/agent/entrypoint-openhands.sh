#!/usr/bin/env bash
# Bootstrap (best-effort) then OpenHands agent-server.
# Must work as non-root: Agent Canvas docker runtime uses
#   --user $(id -u):$(id -g) --cap-drop ALL --security-opt no-new-privileges
set -uo pipefail
# Do NOT use set -e: bootstrap steps may fail without root.

OH_PORT="${OH_PORT:-8000}"
OH_USERNAME="${OH_USERNAME:-openhands}"
export SKIP_DOCTOR="${SKIP_DOCTOR:-1}"
export AGENT_WORKSPACE="${AGENT_WORKSPACE:-/workspace}"
export ORG_CERTS_DIR="${ORG_CERTS_DIR:-/certs}"

log() { printf '[agent-oh] %s\n' "$*"; }

EUID_NUM="$(id -u)"
is_root() { [[ "$EUID_NUM" -eq 0 ]]; }

# --- proxy / certs (never abort) ---
if [[ -x /opt/1c-agent/scripts/apply-proxy.sh ]]; then
  # shellcheck disable=SC1091
  source /opt/1c-agent/scripts/apply-proxy.sh || true
fi
if [[ -f /etc/1c-agent/proxy.env.runtime ]]; then
  # shellcheck disable=SC1091
  source /etc/1c-agent/proxy.env.runtime || true
fi
if is_root && [[ -x /opt/1c-agent/scripts/apply-certs.sh ]]; then
  /opt/1c-agent/scripts/apply-certs.sh || true
elif [[ -f /etc/1c-agent/certs.env ]]; then
  # shellcheck disable=SC1091
  source /etc/1c-agent/certs.env || true
fi

# Corp Cognitum / MITM proxies: some org CAs omit critical Basic Constraints;
# OpenSSL 3 + LiteLLM/aiohttp then fail verify even when the CA is in the store.
# Match tests/.env.integration (LLM_VERIFY_SSL=false). Override with SSL_VERIFY=true.
if [[ "${SSL_VERIFY:-False}" =~ ^([Ff]alse|0|no|NO)$ ]]; then
  export SSL_VERIFY=False
  export LITELLM_SSL_VERIFY=False
  export CURL_CA_BUNDLE="${CURL_CA_BUNDLE:-}"
  # Keep REQUESTS/SSL_CERT_FILE from certs.env when present; LiteLLM still
  # honors SSL_VERIFY=False for outbound LLM calls.
fi

# --- nethasp (conf dir is writable by openhands in the image) ---
if [[ -n "${HASP_SERVER_ADDR:-}" ]]; then
  conf_dir="${NETHASP_DIR:-/opt/1cv8/conf}"
  mkdir -p "$conf_dir" 2>/dev/null || conf_dir="${HOME:-/tmp}/.1cv8/conf"
  mkdir -p "$conf_dir" 2>/dev/null || true
  dest="$conf_dir/nethasp.ini"
  if [[ -f /opt/1c-agent/nethasp.ini.template ]]; then
    sed "s/\${HASP_SERVER_ADDR}/${HASP_SERVER_ADDR}/g" \
      /opt/1c-agent/nethasp.ini.template >"$dest" 2>/dev/null \
      && log "nethasp.ini → $dest (HASP_SERVER_ADDR=$HASP_SERVER_ADDR)" \
      || log "nethasp.ini write skipped (no permission)"
  fi
fi

# --- display (optional; may fail under cap-drop — ignore) ---
DISPLAY="${DISPLAY:-:99}"
export DISPLAY
if [[ "${SKIP_DISPLAY:-0}" != "1" ]]; then
  if ! pgrep -x Xvfb >/dev/null 2>&1; then
    log "Starting Xvfb $DISPLAY"
    Xvfb "$DISPLAY" -screen 0 "${DISPLAY_WIDTH:-1440}x${DISPLAY_HEIGHT:-900}x24" \
      -ac +extension GLX +render -noreset >/tmp/Xvfb.log 2>&1 &
    sleep 0.3
  fi
  if ! pgrep -x openbox >/dev/null 2>&1; then
    openbox >/tmp/openbox.log 2>&1 &
  fi
  if ! pgrep -x x11vnc >/dev/null 2>&1; then
    vnc_args=(-forever -shared -rfbport 5900 -display "$DISPLAY" -nopw)
    if [[ -n "${VNC_PASSWORD:-}" ]]; then
      passfile="$(mktemp /tmp/vncpass.XXXXXX 2>/dev/null || echo /tmp/vncpass.$$)"
      x11vnc -storepasswd "$VNC_PASSWORD" "$passfile" >/dev/null 2>&1 || true
      vnc_args=(-forever -shared -rfbport 5900 -display "$DISPLAY" -rfbauth "$passfile")
    fi
    log "Starting x11vnc :5900"
    x11vnc "${vnc_args[@]}" >/tmp/x11vnc.log 2>&1 &
  fi
fi

mkdir -p "$AGENT_WORKSPACE/project" 2>/dev/null || true
if is_root; then
  chown -R "${OH_USERNAME}:${OH_USERNAME}" "$AGENT_WORKSPACE" 2>/dev/null || true
fi

# Git identity for local commits on the bind-mounted host checkout.
# (No push from entrypoint. remote push stays a manual/host decision.)
if command -v git >/dev/null 2>&1; then
  git config --global --add safe.directory "${AGENT_WORKSPACE}" 2>/dev/null || true
  git config --global --add safe.directory '*' 2>/dev/null || true
  if [[ -n "${GIT_AUTHOR_NAME:-}" ]]; then
    git config --global user.name "${GIT_AUTHOR_NAME}" 2>/dev/null || true
  fi
  if [[ -n "${GIT_AUTHOR_EMAIL:-}" ]]; then
    git config --global user.email "${GIT_AUTHOR_EMAIL}" 2>/dev/null || true
  fi
  export GIT_AUTHOR_NAME="${GIT_AUTHOR_NAME:-OpenHands Agent}"
  export GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-openhands@local}"
  export GIT_COMMITTER_NAME="${GIT_COMMITTER_NAME:-$GIT_AUTHOR_NAME}"
  export GIT_COMMITTER_EMAIL="${GIT_COMMITTER_EMAIL:-$GIT_AUTHOR_EMAIL}"
fi
if [[ -d "${AGENT_WORKSPACE}/.git" ]]; then
  log "workspace git: $(git -C "$AGENT_WORKSPACE" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?') @ $(git -C "$AGENT_WORKSPACE" remote get-url origin 2>/dev/null || echo 'no-origin')"
fi

# Ensure 1c-dev on PATH for non-login shells
if [[ ! -e /usr/local/bin/1c-dev && -x /opt/1c-dev-venv/bin/1c-dev ]]; then
  ln -sfn /opt/1c-dev-venv/bin/1c-dev /usr/local/bin/1c-dev 2>/dev/null || true
fi
export PATH="/opt/1cv8/current:/opt/1C/1CE/components/1cedtcli:/opt/1C/1CE/components/1c-enterprise-ring:/opt/1c-dev-venv/bin:/usr/local/bin:${PATH}"

# Seed baked toolchain (md-reader/docs-facade/apache/…) into user cache.
# Avoids Gradle into read-only site-packages (1CT014) and gcc build on every start.
if [[ -x /opt/1c-agent/scripts/seed-toolchain-cache.sh ]]; then
  /opt/1c-agent/scripts/seed-toolchain-cache.sh || log "seed-toolchain skipped/failed"
fi

# Bridge Settings URLs http://127.0.0.1:<port>/mcp → sibling compose DNS.
# Canvas Test uses host-published 127.0.0.1; conversation uses the same URL via forward.
if [[ "${MCP_LOCAL_FORWARD:-1}" == "1" && -f /opt/1c-agent/scripts/mcp-local-forward.py ]]; then
  if getent hosts bsl-ls >/dev/null 2>&1; then
    python3 /opt/1c-agent/scripts/mcp-local-forward.py \
      "${BSLLS_MCP_PORT:-18767}" bsl-ls "${BSLLS_MCP_PORT:-18767}" \
      >/tmp/mcp-fwd-bsl-ls.log 2>&1 &
    log "mcp-forward bsl-ls on 127.0.0.1:${BSLLS_MCP_PORT:-18767}"
  fi
  if getent hosts v8std-mcp >/dev/null 2>&1; then
    python3 /opt/1c-agent/scripts/mcp-local-forward.py \
      "${V8STD_MCP_PORT:-18766}" v8std-mcp 8000 \
      >/tmp/mcp-fwd-v8std.log 2>&1 &
    log "mcp-forward v8std on 127.0.0.1:${V8STD_MCP_PORT:-18766}"
  fi
fi

# External catalog tools (usually SKIP — siblings in compose).
if [[ -x /opt/1c-agent/scripts/bootstrap-external-tools.sh ]]; then
  /opt/1c-agent/scripts/bootstrap-external-tools.sh || log "tools-bootstrap skipped/failed"
fi
# Optional doctor gate (default off for OH — slow); set SKIP_DOCTOR=0 to enable.
if [[ "${SKIP_DOCTOR:-1}" != "1" ]] && command -v 1c-dev >/dev/null 2>&1; then
  log "Running 1c-dev doctor"
  1c-dev doctor || log "doctor reported issues (continuing)"
fi

# OH docker runtime appends: --host 0.0.0.0 --port 8000
# If no args, supply defaults ourselves.
args=("$@")
if [[ ${#args[@]} -eq 0 ]]; then
  args=(--host 0.0.0.0 --port "$OH_PORT")
fi

log "Starting openhands-agent-server as uid=$EUID_NUM: ${args[*]}"
if is_root && command -v runuser >/dev/null 2>&1 && id "$OH_USERNAME" >/dev/null 2>&1; then
  exec runuser -u "$OH_USERNAME" -- /usr/local/bin/openhands-agent-server "${args[@]}"
fi
exec /usr/local/bin/openhands-agent-server "${args[@]}"
