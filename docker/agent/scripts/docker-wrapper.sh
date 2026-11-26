#!/usr/bin/env bash
# Wrap docker CLI inside Agent Canvas. Docker conversation runtime uses an
# isolated empty /workspace and the UI blocks host folders; replace that
# bind with GIT_REPO_HOST_PATH for 1c-agent-oh runs.
#
# Also join the compose project network so conversation resolves sibling MCP
# DNS names (bsl-ls, v8std, …).
#
# IMPORTANT: -v paths are resolved by the *host* dockerd via the mounted
# socket. The path does NOT need to exist inside the Canvas container.
# Newer dockerd rejects duplicate mount points — strip OH's /workspace first.
set -euo pipefail

REAL_DOCKER="${REAL_DOCKER:-/usr/bin/docker}"

if [[ "${1:-}" != "run" ]]; then
  exec "$REAL_DOCKER" "$@"
fi

REPO_HOST="${OH_INJECT_GIT_REPO_HOST_PATH:-}"
IMAGE_RE="${OH_INJECT_IMAGE_MATCH:-1c-agent-oh}"
CACHE_HOST="${OH_INJECT_TOOLCHAIN_CACHE_HOST:-}"
SHARE_HOST="${OH_INJECT_TOOLS_SHARE_HOST:-}"
# Compose project network (name: 1c-agent → 1c-agent_default)
COMPOSE_NET="${OH_INJECT_COMPOSE_NETWORK:-1c-agent_default}"

ours=0
for a in "$@"; do
  if [[ "$a" == *"$IMAGE_RE"* && "$a" != -* ]]; then
    ours=1
    break
  fi
done
if [[ "$ours" -eq 0 ]]; then
  exec "$REAL_DOCKER" "$@"
fi

# Nothing to inject → passthrough
if [[ -z "$REPO_HOST" && -z "$CACHE_HOST" && -z "$SHARE_HOST" && -z "$COMPOSE_NET" ]]; then
  exec "$REAL_DOCKER" "$@"
fi

is_workspace_mount() {
  local spec="$1"
  case "$spec" in
    *:/workspace | *:/workspace:*) return 0 ;;
    *) return 1 ;;
  esac
}

out=()
injected=0
i=1
while [[ $i -le $# ]]; do
  a="${!i}"
  # Drop -v/--volume that already targets /workspace (OH empty runtime dir).
  if [[ "$a" == "-v" || "$a" == "--volume" ]]; then
    next=$((i + 1))
    if [[ $next -le $# ]] && is_workspace_mount "${!next}"; then
      i=$((i + 2))
      continue
    fi
    out+=("$a" "${!next}")
    i=$((i + 2))
    continue
  fi
  # Drop OH's --network so we can attach to the compose stack network.
  if [[ -n "$COMPOSE_NET" && ( "$a" == "--network" || "$a" == "--net" ) ]]; then
    i=$((i + 2))
    continue
  fi
  if [[ -n "$COMPOSE_NET" && "$a" == --network=* ]]; then
    i=$((i + 1))
    continue
  fi
  if [[ -n "$COMPOSE_NET" && "$a" == --net=* ]]; then
    i=$((i + 1))
    continue
  fi
  # Insert mounts / network immediately before the conversation image.
  if [[ "$injected" -eq 0 && "$a" == *"$IMAGE_RE"* && "$a" != -* ]]; then
    if [[ -n "$REPO_HOST" ]]; then
      printf '[docker-wrapper] /workspace <- %s\n' "$REPO_HOST" >&2
      out+=(
        -v "${REPO_HOST}:/workspace"
        -e "GIT_REPO_URL=${OH_INJECT_GIT_REPO_URL:-}"
        -e "GIT_BRANCH=${OH_INJECT_GIT_BRANCH:-}"
        -e "GIT_AUTHOR_NAME=${GIT_AUTHOR_NAME:-OpenHands Agent}"
        -e "GIT_AUTHOR_EMAIL=${GIT_AUTHOR_EMAIL:-openhands@local}"
        -e "GIT_COMMITTER_NAME=${GIT_COMMITTER_NAME:-${GIT_AUTHOR_NAME:-OpenHands Agent}}"
        -e "GIT_COMMITTER_EMAIL=${GIT_COMMITTER_EMAIL:-${GIT_AUTHOR_EMAIL:-openhands@local}}"
      )
    fi
    if [[ -n "$CACHE_HOST" ]]; then
      mkdir -p "$CACHE_HOST" 2>/dev/null || true
      printf '[docker-wrapper] toolchain cache <- %s\n' "$CACHE_HOST" >&2
      out+=(-v "${CACHE_HOST}:/var/openhands/.openhands/.cache/1c-dev")
    fi
    if [[ -n "$SHARE_HOST" ]]; then
      mkdir -p "$SHARE_HOST" 2>/dev/null || true
      printf '[docker-wrapper] tools share <- %s\n' "$SHARE_HOST" >&2
      out+=(-v "${SHARE_HOST}:/var/openhands/.openhands/.local/share/1c-dev")
    fi
    if [[ -n "$COMPOSE_NET" ]]; then
      printf '[docker-wrapper] network <- %s\n' "$COMPOSE_NET" >&2
      out+=(--network "$COMPOSE_NET")
    fi
    # Sibling MCP live in compose — skip in-container tools install / services up.
    # NO_PROXY must include 127.0.0.1 (Settings URLs) and compose DNS names.
    _no_proxy="${NO_PROXY:-localhost,127.0.0.1,::1,.local,host.docker.internal,bsl-ls,v8std-mcp,v8std,v8std-site,mcp}"
    out+=(
      -e "SKIP_TOOLS_BOOTSTRAP=${SKIP_TOOLS_BOOTSTRAP:-1}"
      -e "TOOLS_BOOTSTRAP_SERVICES=${TOOLS_BOOTSTRAP_SERVICES:-}"
      -e "TOOLS_BOOTSTRAP_FORCE=${TOOLS_BOOTSTRAP_FORCE:-0}"
      -e "ONEC_TOOLCHAIN_BAKE=${ONEC_TOOLCHAIN_BAKE:-/opt/1c-dev-cache/1c-dev}"
      -e "MCP_LOCAL_FORWARD=${MCP_LOCAL_FORWARD:-1}"
      -e "NO_PROXY=${_no_proxy}"
      -e "no_proxy=${_no_proxy}"
    )
    injected=1
  fi
  out+=("$a")
  i=$((i + 1))
done

exec "$REAL_DOCKER" "${out[@]}"
