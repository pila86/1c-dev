#!/usr/bin/env bash
# Build 1c-agent-base (if needed) and 1c-agent-oh.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

# Load docker/agent/.env so proxy/HASP bake-args are not empty by accident.
ENV_FILE="${ENV_FILE:-$ROOT/docker/agent/.env}"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

ONEC_VERSION="${ONEC_VERSION:-8.5.1.1529}"
EDT_VERSION="${EDT_VERSION:-2026.2.2}"
OH_AGENT_SERVER_VERSION="${OH_AGENT_SERVER_VERSION:-1.64.1}"
BASE_TAG="${BASE_TAG:-1c-agent-base:${ONEC_VERSION%.*}-edt${EDT_VERSION%.*}}"
# prettier default matching README
BASE_TAG="${BASE_IMAGE_TAG:-1c-agent-base:8.5.1-edt2026.2}"
OH_TAG="${OH_IMAGE_TAG:-1c-agent-oh:8.5.1-edt2026.2}"

if [[ "${SKIP_BASE:-0}" != "1" ]]; then
  echo "==> Building $BASE_TAG (toolchain sync needs network/proxy)"
  echo "    HTTP_PROXY=${HTTP_PROXY:-<empty>}"
  docker build \
    --build-arg ONEC_VERSION="$ONEC_VERSION" \
    --build-arg EDT_VERSION="$EDT_VERSION" \
    --build-arg HTTP_PROXY="${HTTP_PROXY:-}" \
    --build-arg HTTPS_PROXY="${HTTPS_PROXY:-${HTTP_PROXY:-}}" \
    --build-arg NO_PROXY="${NO_PROXY:-localhost,127.0.0.1,::1,.local,host.docker.internal}" \
    -t "$BASE_TAG" \
    -f docker/agent/Dockerfile.base \
    .
fi

echo "==> Building $OH_TAG (agent-server $OH_AGENT_SERVER_VERSION)"
echo "    HTTP_PROXY=${HTTP_PROXY:-<empty>} HASP_SERVER_ADDR=${HASP_SERVER_ADDR:-<empty>}"
# Bake proxy/HASP into image: conversation containers do not inherit Canvas env.
# Git workspace is a host bind-mount (GIT_REPO_HOST_PATH via docker-wrapper), not baked.
docker build \
  --build-arg BASE_IMAGE="$BASE_TAG" \
  --build-arg OH_AGENT_SERVER_VERSION="$OH_AGENT_SERVER_VERSION" \
  --build-arg HTTP_PROXY="${HTTP_PROXY:-}" \
  --build-arg HTTPS_PROXY="${HTTPS_PROXY:-${HTTP_PROXY:-}}" \
  --build-arg NO_PROXY="${NO_PROXY:-localhost,127.0.0.1,::1,.local,host.docker.internal}" \
  --build-arg HASP_SERVER_ADDR="${HASP_SERVER_ADDR:-}" \
  -t "$OH_TAG" \
  -f docker/agent/Dockerfile.openhands \
  docker/agent

echo "OK: $OH_TAG"
echo "Next: docker compose -f docker/agent/compose.yml --env-file docker/agent/.env up"
