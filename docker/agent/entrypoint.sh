#!/usr/bin/env bash
# Runtime bootstrap: proxy, org certs, nethasp.ini, Xvfb/VNC, optional doctor gate.
set -euo pipefail

DISPLAY="${DISPLAY:-:99}"
DISPLAY_WIDTH="${DISPLAY_WIDTH:-1440}"
DISPLAY_HEIGHT="${DISPLAY_HEIGHT:-900}"
VNC_PASSWORD="${VNC_PASSWORD:-}"
HASP_SERVER_ADDR="${HASP_SERVER_ADDR:-}"
NETHASP_DIR="${NETHASP_DIR:-/opt/1cv8/conf}"
SKIP_DOCTOR="${SKIP_DOCTOR:-0}"
AGENT_WORKSPACE="${AGENT_WORKSPACE:-/workspace}"
ORG_CERTS_DIR="${ORG_CERTS_DIR:-/certs}"

log() { printf '[agent-entrypoint] %s\n' "$*"; }

apply_network_trust() {
  mkdir -p /etc/1c-agent
  if [[ -x /opt/1c-agent/scripts/apply-proxy.sh ]]; then
    # shellcheck disable=SC1091
    source /opt/1c-agent/scripts/apply-proxy.sh || true
  fi
  if [[ -f /etc/1c-agent/proxy.env.runtime ]]; then
    # shellcheck disable=SC1091
    source /etc/1c-agent/proxy.env.runtime
  fi
  if [[ -x /opt/1c-agent/scripts/apply-certs.sh ]]; then
    ORG_CERTS_DIR="$ORG_CERTS_DIR" /opt/1c-agent/scripts/apply-certs.sh || true
  fi
  if [[ -f /etc/1c-agent/certs.env ]]; then
    # shellcheck disable=SC1091
    source /etc/1c-agent/certs.env
  fi
}

write_nethasp() {
  mkdir -p "$NETHASP_DIR"
  local dest="$NETHASP_DIR/nethasp.ini"
  if [[ -z "$HASP_SERVER_ADDR" ]]; then
    log "HASP_SERVER_ADDR not set — skip nethasp.ini (license may fail)"
    return 0
  fi
  if [[ -f /opt/1c-agent/nethasp.ini.template ]]; then
    sed "s/\${HASP_SERVER_ADDR}/${HASP_SERVER_ADDR}/g" \
      /opt/1c-agent/nethasp.ini.template >"$dest"
  else
    cat >"$dest" <<EOF
[NH_COMMON]
NH_TCPIP=Enabled
NH_IPX=Disabled
NH_NETBIOS=Disabled

[NH_TCPIP]
NH_SERVER_ADDR=${HASP_SERVER_ADDR}
NH_PORT_NUMBER=475
NH_TCPIP_METHOD=UDP
NH_USE_BROADCAST=Disabled
EOF
  fi
  log "Wrote $dest (HASP_SERVER_ADDR=$HASP_SERVER_ADDR)"
}

probe_hasp() {
  if [[ -z "$HASP_SERVER_ADDR" ]]; then
    return 0
  fi
  if command -v nc >/dev/null 2>&1; then
    if nc -u -z -w 2 "$HASP_SERVER_ADDR" 475 2>/dev/null; then
      log "HASP UDP/475 probe: ok ($HASP_SERVER_ADDR)"
    else
      log "HASP UDP/475 probe: no response from $HASP_SERVER_ADDR (continuing)"
    fi
  else
    log "nc not available — skip HASP probe"
  fi
}

start_display() {
  export DISPLAY
  if [[ "${SKIP_DISPLAY:-0}" == "1" ]]; then
    log "SKIP_DISPLAY=1 — leave display to another stack"
    return 0
  fi
  if [[ -S "/tmp/.X11-unix/X${DISPLAY#:}" ]] || pgrep -x Xvfb >/dev/null 2>&1; then
    log "Xvfb already running on $DISPLAY"
  else
    log "Starting Xvfb $DISPLAY ${DISPLAY_WIDTH}x${DISPLAY_HEIGHT}x24"
    Xvfb "$DISPLAY" -screen 0 "${DISPLAY_WIDTH}x${DISPLAY_HEIGHT}x24" -ac +extension GLX +render -noreset &
    sleep 0.5
  fi

  if ! pgrep -x openbox >/dev/null 2>&1; then
    openbox >/tmp/openbox.log 2>&1 &
  fi

  if ! pgrep -x x11vnc >/dev/null 2>&1; then
    # Do not pass -localhost: we need VNC reachable via published port.
    local vnc_args=(-forever -shared -rfbport 5900 -display "$DISPLAY")
    if [[ -n "$VNC_PASSWORD" ]]; then
      local passfile
      passfile="$(mktemp /tmp/vncpass.XXXXXX)"
      x11vnc -storepasswd "$VNC_PASSWORD" "$passfile" >/dev/null 2>&1
      vnc_args+=(-rfbauth "$passfile")
    else
      vnc_args+=(-nopw)
      log "VNC without password (set VNC_PASSWORD for auth)"
    fi
    log "Starting x11vnc on :5900"
    x11vnc "${vnc_args[@]}" >/tmp/x11vnc.log 2>&1 &
  fi
}

run_doctor() {
  if [[ "$SKIP_DOCTOR" == "1" ]]; then
    log "SKIP_DOCTOR=1 — skip doctor"
    return 0
  fi
  if ! command -v 1c-dev >/dev/null 2>&1; then
    log "1c-dev not in PATH — skip doctor"
    return 0
  fi
  log "Running 1c-dev doctor"
  if 1c-dev doctor; then
    log "doctor: ok"
  else
    log "doctor: reported issues (continuing; set SKIP_DOCTOR=1 to silence)"
  fi
}

apply_network_trust
write_nethasp
probe_hasp
start_display
export DISPLAY

if [[ -x /opt/1c-agent/scripts/seed-toolchain-cache.sh ]]; then
  /opt/1c-agent/scripts/seed-toolchain-cache.sh || log "seed-toolchain skipped/failed"
fi
if [[ -x /opt/1c-agent/scripts/bootstrap-external-tools.sh ]]; then
  /opt/1c-agent/scripts/bootstrap-external-tools.sh || log "tools-bootstrap skipped/failed"
fi

run_doctor

mkdir -p "$AGENT_WORKSPACE"
cd "$AGENT_WORKSPACE"

if command -v git >/dev/null 2>&1; then
  git config --global --add safe.directory "$AGENT_WORKSPACE" 2>/dev/null || true
  if [[ -n "${GIT_AUTHOR_NAME:-}" ]]; then
    git config --global user.name "$GIT_AUTHOR_NAME" 2>/dev/null || true
  fi
  if [[ -n "${GIT_AUTHOR_EMAIL:-}" ]]; then
    git config --global user.email "$GIT_AUTHOR_EMAIL" 2>/dev/null || true
  fi
fi

if [[ "$#" -eq 0 ]]; then
  exec bash
else
  exec "$@"
fi
