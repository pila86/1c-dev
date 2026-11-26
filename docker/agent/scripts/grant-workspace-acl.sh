#!/usr/bin/env bash
# Allow conversation uid 10001 (openhands) to commit on a host checkout.
# Uses POSIX ACL; does not chown the tree away from the developer.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/docker/agent/.env}"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

target="${1:-${GIT_REPO_HOST_PATH:-}}"
uid="${OH_WORKSPACE_UID:-10001}"

if [[ -z "$target" || ! -d "$target" ]]; then
  echo "usage: $0 /path/to/checkout   (or set GIT_REPO_HOST_PATH)" >&2
  exit 1
fi
if ! command -v setfacl >/dev/null 2>&1; then
  echo "setfacl not found — install acl package" >&2
  exit 1
fi

echo "[acl] grant u:${uid}:rwX (default+access) on $target"
setfacl -R -m "u:${uid}:rwX" "$target"
setfacl -R -d -m "u:${uid}:rwX" "$target"
# smoke
docker run --rm --user "${uid}:${uid}" -v "$target:/workspace" alpine:3.20 \
  sh -c 'touch /workspace/.oh-acl-ok && rm /workspace/.oh-acl-ok && echo OK'
echo "[acl] done — commits as uid ${uid} should work; push remains your choice on the host"
