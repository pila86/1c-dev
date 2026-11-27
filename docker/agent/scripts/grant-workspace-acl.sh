#!/usr/bin/env bash
# Allow conversation uid 10001 (openhands) to commit on host checkouts.
# Uses POSIX ACL; does not chown the tree away from the developer.
#
# Normally openhands-init applies the same ACL on every `compose up`.
# Use this script to refresh ACL without restarting the stack (e.g. after a new clone).
#
# Usage:
#   ./grant-workspace-acl.sh                  # OH_PROJECT_SLUGS or all under OH_WORKSPACES_ROOT
#   ./grant-workspace-acl.sh /path/to/one     # single checkout
set -euo pipefail
AGENT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$AGENT_DIR/.env}"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

uid="${OH_WORKSPACE_UID:-10001}"
workspaces_root="${OH_WORKSPACES_ROOT:-}"
allowlist="${OH_PROJECT_SLUGS:-}"

if ! command -v setfacl >/dev/null 2>&1; then
  echo "setfacl not found — install acl package" >&2
  exit 1
fi

grant_one() {
  local target="$1"
  if [[ ! -d "$target" ]]; then
    echo "[acl] skip missing dir: $target" >&2
    return 0
  fi
  echo "[acl] grant u:${uid}:rwX (default+access) on $target"
  # Some trees have root-owned / immutable bits — best-effort.
  setfacl -R -m "u:${uid}:rwX" "$target" || true
  setfacl -R -d -m "u:${uid}:rwX" "$target" || true
  docker run --rm --user "${uid}:${uid}" -v "$target:/workspace" alpine:3.20 \
    sh -c 'touch /workspace/.oh-acl-ok && rm /workspace/.oh-acl-ok && echo OK'
}

if [[ $# -ge 1 ]]; then
  grant_one "$1"
  echo "[acl] done — commits as uid ${uid} should work; push remains your choice on the host"
  exit 0
fi

if [[ -z "$workspaces_root" || ! -d "$workspaces_root" ]]; then
  echo "usage: $0 [/path/to/checkout]" >&2
  echo "  or set OH_WORKSPACES_ROOT (and optional OH_PROJECT_SLUGS) in .env" >&2
  exit 1
fi

mapfile -t dirs < <(
  if [[ -n "$allowlist" ]]; then
    IFS=',' read -r -a slugs <<< "$allowlist"
    for s in "${slugs[@]}"; do
      s="${s// /}"
      [[ -n "$s" ]] || continue
      printf '%s\n' "$workspaces_root/$s"
    done
  else
    find "$workspaces_root" -mindepth 1 -maxdepth 1 -type d ! -name '.*' | sort
  fi
)

if [[ ${#dirs[@]} -eq 0 ]]; then
  echo "[acl] no project dirs under $workspaces_root" >&2
  exit 1
fi

for d in "${dirs[@]}"; do
  grant_one "$d"
done
echo "[acl] done — commits as uid ${uid} should work; push remains your choice on the host"
