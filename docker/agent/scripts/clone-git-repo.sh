#!/usr/bin/env bash
# Idempotent checkout of GIT_REPO_URL into a target directory.
# Auth: GIT_TOKEN (HTTPS) or host SSH (git@ / ssh://). Optional local
# GIT_REPO_HOST_PATH speeds up the first clone via local git clone.
#
# Env:
#   GIT_REPO_URL          required (unless target already has .git)
#   GIT_CLONE_DIR         target path (default: $AGENT_WORKSPACE or /workspace)
#   GIT_BRANCH            optional branch/tag after clone
#   GIT_TOKEN             HTTPS token (username defaults to oauth2 / GIT_USERNAME)
#   GIT_USERNAME          HTTPS username (default: oauth2)
#   GIT_REPO_HOST_PATH    existing local checkout used as clone source
#   GIT_CLONE_DEPTH       0 = full history; >0 = shallow (default 0)
#   GIT_PULL_ON_START     1 = fetch+ff-only when target already exists
#   GIT_SSH_COMMAND       optional override for SSH clone
set -uo pipefail

log() { printf '[git-clone] %s\n' "$*"; }

url="${GIT_REPO_URL:-}"
target="${GIT_CLONE_DIR:-${AGENT_WORKSPACE:-/workspace}}"
branch="${GIT_BRANCH:-}"
depth="${GIT_CLONE_DEPTH:-0}"
host_path="${GIT_REPO_HOST_PATH:-}"
pull_on_start="${GIT_PULL_ON_START:-0}"
token="${GIT_TOKEN:-${GITLAB_TOKEN:-${GIT_PRIVATE_TOKEN:-}}}"
username="${GIT_USERNAME:-oauth2}"

if [[ -z "$url" && ! -d "$target/.git" && -z "$host_path" ]]; then
  log "GIT_REPO_URL not set — skip"
  exit 0
fi

mkdir -p "$(dirname "$target")" 2>/dev/null || true

workspace_is_placeholder() {
  # OpenHands seeds an empty /workspace/project; treat as empty for clone-into.
  local entries
  entries="$(find "$target" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l | tr -d ' ')"
  [[ "$entries" -eq 0 ]] && return 0
  if [[ "$entries" -eq 1 && -d "$target/project" ]]; then
    local inner
    inner="$(find "$target/project" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l | tr -d ' ')"
    [[ "$inner" -eq 0 ]] && return 0
  fi
  return 1
}

auth_url() {
  local raw="$1"
  if [[ -z "$token" ]]; then
    printf '%s\n' "$raw"
    return 0
  fi
  case "$raw" in
    https://* | http://*)
      local rest="${raw#*://}"
      printf 'https://%s:%s@%s\n' "$username" "$token" "$rest"
      ;;
    *)
      printf '%s\n' "$raw"
      ;;
  esac
}

https_to_ssh() {
  local raw="$1"
  if [[ "$raw" =~ ^https?://([^/]+)/(.+?)(\.git)?$ ]]; then
    printf 'git@%s:%s.git\n' "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]%.git}"
  else
    printf '%s\n' "$raw"
  fi
}

clone_url() {
  local raw="$1"
  if [[ -n "$token" ]]; then
    auth_url "$raw"
    return 0
  fi
  case "$raw" in
    https://* | http://*)
      # Prefer SSH when no token (corp GitLab + ProxyCommand on host).
      https_to_ssh "$raw"
      ;;
    *)
      printf '%s\n' "$raw"
      ;;
  esac
}

run_git() {
  GIT_TERMINAL_PROMPT=0 git "$@"
}

ensure_branch() {
  if [[ -z "$branch" ]]; then
    return 0
  fi
  if run_git -C "$target" rev-parse --verify "refs/heads/$branch" >/dev/null 2>&1; then
    run_git -C "$target" checkout "$branch" >/dev/null
  elif run_git -C "$target" rev-parse --verify "refs/remotes/origin/$branch" >/dev/null 2>&1; then
    run_git -C "$target" checkout -B "$branch" "origin/$branch" >/dev/null
  else
    run_git -C "$target" fetch origin "$branch" >/dev/null 2>&1 || true
    run_git -C "$target" checkout -B "$branch" "origin/$branch" >/dev/null 2>&1 \
      || run_git -C "$target" checkout "$branch" >/dev/null 2>&1 \
      || log "branch '$branch' not found — left on $(run_git -C "$target" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
  fi
}

if [[ -d "$target/.git" ]]; then
  log "already a git repo: $target"
  if [[ "$pull_on_start" == "1" ]]; then
    log "GIT_PULL_ON_START=1 — fetch + ff-only"
    run_git -C "$target" fetch --all --prune 2>&1 | tail -n 5 || true
    ensure_branch
    run_git -C "$target" merge --ff-only @{u} 2>&1 | tail -n 5 || true
  else
    ensure_branch
  fi
  log "ready: $(run_git -C "$target" remote get-url origin 2>/dev/null || echo no-origin) @ $(run_git -C "$target" rev-parse --abbrev-ref HEAD 2>/dev/null)"
  exit 0
fi

if [[ -e "$target" ]] && ! workspace_is_placeholder; then
  log "ERROR: $target is not empty and has no .git — refuse to clone"
  exit 1
fi

# Clear OH placeholder before clone-into-place.
if [[ -d "$target/project" ]] && workspace_is_placeholder; then
  rm -rf "$target/project" 2>/dev/null || true
fi

mkdir -p "$target"
depth_args=()
if [[ "$depth" =~ ^[1-9][0-9]*$ ]]; then
  depth_args=(--depth "$depth")
fi

tmp="$(mktemp -d "${TMPDIR:-/tmp}/git-clone.XXXXXX")"
cleanup() { rm -rf "$tmp"; }
trap cleanup EXIT

cloned=0
if [[ -n "$host_path" && -d "$host_path/.git" ]]; then
  log "local clone from $host_path → $target"
  if run_git clone "${depth_args[@]}" -- "$host_path" "$tmp/repo" 2>&1; then
    cloned=1
    if [[ -n "$url" ]]; then
      # Keep a usable remote: SSH when no HTTPS token (corp GitLab).
      clean_url="$url"
      if [[ -z "$token" ]]; then
        case "$url" in
          https://* | http://*) clean_url="$(https_to_ssh "$url")" ;;
        esac
      fi
      run_git -C "$tmp/repo" remote set-url origin "$clean_url" 2>/dev/null || true
    fi
  else
    log "local clone failed — fall back to remote"
  fi
fi

if [[ "$cloned" -eq 0 ]]; then
  if [[ -z "$url" ]]; then
    log "ERROR: no GIT_REPO_URL and local clone unavailable"
    exit 1
  fi
  remote="$(clone_url "$url")"
  # Never print credentials.
  log "cloning $(printf '%s' "$url" | sed -E 's#://[^/@]*@#://***@#') → $target"
  if ! run_git clone "${depth_args[@]}" -- "$remote" "$tmp/repo" 2>&1; then
    log "ERROR: git clone failed"
    exit 1
  fi
  # Rewrite origin to clean URL (no embedded token).
  run_git -C "$tmp/repo" remote set-url origin "$url" 2>/dev/null || true
fi

# Move into target (may already exist as empty dir).
shopt -s dotglob nullglob
# shellcheck disable=SC2086
mv "$tmp/repo"/* "$target"/ 2>/dev/null || true
# mv of .git specifically if glob missed
if [[ -e "$tmp/repo/.git" && ! -e "$target/.git" ]]; then
  mv "$tmp/repo/.git" "$target/.git"
fi
shopt -u dotglob nullglob
rm -rf "$tmp/repo"

ensure_branch
log "ready: $(run_git -C "$target" remote get-url origin 2>/dev/null) @ $(run_git -C "$target" rev-parse --abbrev-ref HEAD 2>/dev/null)"
exit 0
