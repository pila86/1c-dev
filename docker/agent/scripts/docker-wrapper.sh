#!/usr/bin/env bash
# Wrap docker CLI inside Agent Canvas. Docker conversation runtime uses an
# isolated empty /workspace and the UI blocks host folders; replace that
# bind with OH_WORKSPACES_ROOT/<agent-profile-slug> for 1c-agent-oh runs.
#
# Also join the compose project network so conversation resolves sibling MCP
# DNS names (bsl-ls, v8std, …).
#
# IMPORTANT: -v paths are resolved by the *host* dockerd via the mounted
# socket. The path does NOT need to exist inside the Canvas container.
# Newer dockerd rejects duplicate mount points — strip OH's /workspace first.
set -euo pipefail

REAL_DOCKER="${REAL_DOCKER:-/usr/bin/docker}"
RESOLVE_PY="${OH_RESOLVE_WORKSPACE_PY:-/usr/local/bin/resolve-oh-workspace.py}"

if [[ "${1:-}" != "run" ]]; then
  exec "$REAL_DOCKER" "$@"
fi

WORKSPACES_ROOT="${OH_INJECT_WORKSPACES_ROOT:-${OH_WORKSPACES_ROOT:-}}"
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
if [[ -z "$WORKSPACES_ROOT" && -z "$CACHE_HOST" && -z "$SHARE_HOST" && -z "$COMPOSE_NET" ]]; then
  exec "$REAL_DOCKER" "$@"
fi

# Canvas passes `-e OH_RUNTIME_LAUNCHED_PROFILE` *without* `=value`.
# Docker then copies the var from this process environment into the container.
# The JSON is therefore available here as $OH_RUNTIME_LAUNCHED_PROFILE.
extract_launched_profile_id() {
  local raw="${OH_RUNTIME_LAUNCHED_PROFILE:-}"
  if [[ -z "$raw" ]]; then
    return 1
  fi
  python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d.get("agent_profile_id") or "")' \
    "$raw" 2>/dev/null || return 1
}

# Compact conversation id in OH_CONVERSATION_WORKTREE_ROOT (.../runtime-data/<32hex>/…)
extract_conversation_id_from_env() {
  local val="${OH_CONVERSATION_WORKTREE_ROOT:-}"
  if [[ "$val" =~ runtime-data/([0-9a-fA-F]{32})(/|$) ]]; then
    printf '%s\n' "${BASH_REMATCH[1]}"
    return 0
  fi
  # Volume path also contains compact id.
  local i=1 a
  while [[ $i -le $# ]]; do
    a="${!i}"
    if [[ "$a" =~ runtime-data/([0-9a-fA-F]{32})/ ]]; then
      printf '%s\n' "${BASH_REMATCH[1]}"
      return 0
    fi
    i=$((i + 1))
  done
  return 1
}

resolve_repo_host() {
  local profile_id="${1:-}"
  local conv_id="${2:-}"
  local path=""
  local args=()
  if [[ ! -f "$RESOLVE_PY" ]]; then
    printf '[docker-wrapper] WARN: resolve script missing (%s)\n' "$RESOLVE_PY" >&2
  else
    if [[ -n "$profile_id" ]]; then
      args+=(--profile-id "$profile_id")
    fi
    if [[ -n "$conv_id" ]]; then
      args+=(--conversation-id "$conv_id")
    fi
    if [[ ${#args[@]} -gt 0 ]]; then
      if path="$(python3 "$RESOLVE_PY" "${args[@]}")"; then
        if [[ -n "$path" ]]; then
          printf '%s\n' "$path"
          return 0
        fi
      else
        printf '[docker-wrapper] ERROR: resolve-oh-workspace failed\n' >&2
        return 1
      fi
    fi
  fi
  local def="${OH_DEFAULT_PROJECT:-}"
  if [[ -z "$WORKSPACES_ROOT" || -z "$def" ]]; then
    printf '[docker-wrapper] ERROR: cannot resolve workspace (root=%q default=%q)\n' \
      "$WORKSPACES_ROOT" "$def" >&2
    return 1
  fi
  printf '%s/%s\n' "${WORKSPACES_ROOT%/}" "$def"
}

is_workspace_mount() {
  local spec="$1"
  case "$spec" in
    *:/workspace | *:/workspace:*) return 0 ;;
    *) return 1 ;;
  esac
}

REPO_HOST=""
if [[ -n "$WORKSPACES_ROOT" ]]; then
  PROFILE_ID="$(extract_launched_profile_id "$@" || true)"
  CONV_ID="$(extract_conversation_id_from_env "$@" || true)"
  printf '[docker-wrapper] resolve profile_id=%q conv_id=%q\n' \
    "${PROFILE_ID:-}" "${CONV_ID:-}" >&2
  if ! REPO_HOST="$(resolve_repo_host "$PROFILE_ID" "$CONV_ID")"; then
    exit 1
  fi
fi

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
        -e "OH_PROJECT_SLUG=${REPO_HOST##*/}"
        -e "GIT_AUTHOR_NAME=${GIT_AUTHOR_NAME:-OpenHands Agent}"
        -e "GIT_AUTHOR_EMAIL=${GIT_AUTHOR_EMAIL:-openhands@local}"
        -e "GIT_COMMITTER_NAME=${GIT_COMMITTER_NAME:-${GIT_AUTHOR_NAME:-OpenHands Agent}}"
        -e "GIT_COMMITTER_EMAIL=${GIT_COMMITTER_EMAIL:-${GIT_AUTHOR_EMAIL:-openhands@local}}"
      )
    fi
    if [[ -n "$CACHE_HOST" ]]; then
      # Host path or named volume (e.g. 1c-agent_toolchain_cache).
      if [[ "$CACHE_HOST" == /* ]]; then
        mkdir -p "$CACHE_HOST" 2>/dev/null || true
      fi
      printf '[docker-wrapper] toolchain cache <- %s\n' "$CACHE_HOST" >&2
      out+=(-v "${CACHE_HOST}:/var/openhands/.openhands/.cache/1c-dev")
    fi
    if [[ -n "$SHARE_HOST" ]]; then
      if [[ "$SHARE_HOST" == /* ]]; then
        mkdir -p "$SHARE_HOST" 2>/dev/null || true
      fi
      printf '[docker-wrapper] tools share <- %s\n' "$SHARE_HOST" >&2
      out+=(-v "${SHARE_HOST}:/var/openhands/.openhands/.local/share/1c-dev")
    fi
    if [[ -n "$COMPOSE_NET" ]]; then
      printf '[docker-wrapper] network <- %s\n' "$COMPOSE_NET" >&2
      out+=(--network "$COMPOSE_NET")
    fi
    # Sibling MCP live in compose. NO_PROXY: Settings 127.0.0.1 + compose DNS.
    _no_proxy="${NO_PROXY:-localhost,127.0.0.1,::1,.local,host.docker.internal,bsl-ls,v8std-mcp,v8std,v8std-site,mcp,mcp-atlassian}"
    out+=(
      -e "ONEC_TOOLCHAIN_BAKE=${ONEC_TOOLCHAIN_BAKE:-/opt/1c-dev-cache/1c-dev}"
      -e "MCP_LOCAL_FORWARD=${MCP_LOCAL_FORWARD:-1}"
      -e "BSLLS_MCP_PORT=${BSLLS_MCP_PORT:-18767}"
      -e "V8STD_MCP_PORT=${V8STD_MCP_PORT:-18766}"
      -e "MCP_ATLASSIAN_PORT=${MCP_ATLASSIAN_PORT:-18768}"
      -e "NO_PROXY=${_no_proxy}"
      -e "no_proxy=${_no_proxy}"
    )
    # Host entrypoint / scripts override (MCP forwarders etc.). Paths are
    # resolved by *host* dockerd via the socket — absolute on the host.
    if [[ -n "${OH_INJECT_OH_ENTRYPOINT:-}" ]]; then
      printf '[docker-wrapper] entrypoint <- %s\n' "$OH_INJECT_OH_ENTRYPOINT" >&2
      out+=(-v "${OH_INJECT_OH_ENTRYPOINT}:/usr/local/bin/agent-entrypoint-oh.sh:ro")
    fi
    if [[ -n "${OH_INJECT_OH_SCRIPTS:-}" ]]; then
      printf '[docker-wrapper] scripts <- %s\n' "$OH_INJECT_OH_SCRIPTS" >&2
      out+=(-v "${OH_INJECT_OH_SCRIPTS}:/opt/1c-agent/scripts:ro")
    fi
    injected=1
  fi
  out+=("$a")
  i=$((i + 1))
done

exec "$REAL_DOCKER" "${out[@]}"
