#!/usr/bin/env bash
# Host-side: ensure GIT_REPO_URL is checked out under PROJECTS_DIR before Canvas.
# Uses the developer's git/SSH (corp SOCKS ProxyCommand in ~/.ssh/config).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
AGENT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${ENV_FILE:-$AGENT_DIR/.env}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

if [[ -z "${GIT_REPO_URL:-}" && -z "${GIT_REPO_HOST_PATH:-}" ]]; then
  echo "[ensure-repo] GIT_REPO_URL not set — skip"
  exit 0
fi

projects="${PROJECTS_DIR:-$AGENT_DIR/projects}"
# Resolve relative PROJECTS_DIR against agent dir
if [[ "$projects" != /* ]]; then
  projects="$AGENT_DIR/$projects"
fi
name="${GIT_CLONE_NAME:-}"
if [[ -z "$name" ]]; then
  raw="${GIT_REPO_URL:-${GIT_REPO_HOST_PATH:-repo}}"
  name="$(basename "${raw%.git}")"
fi
export GIT_CLONE_DIR="${GIT_CLONE_DIR:-$projects/$name}"
export GIT_REPO_URL="${GIT_REPO_URL:-}"
export GIT_BRANCH="${GIT_BRANCH:-}"
export GIT_REPO_HOST_PATH="${GIT_REPO_HOST_PATH:-}"
export GIT_CLONE_DEPTH="${GIT_CLONE_DEPTH:-0}"
export GIT_PULL_ON_START="${GIT_PULL_ON_START:-0}"
export GIT_TOKEN="${GIT_TOKEN:-}"
export GIT_USERNAME="${GIT_USERNAME:-oauth2}"

mkdir -p "$projects"
chmod 777 "$projects" 2>/dev/null || true

echo "[ensure-repo] → $GIT_CLONE_DIR"
exec "$AGENT_DIR/scripts/clone-git-repo.sh"
