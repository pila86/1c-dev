#!/usr/bin/env bash
# Copy baked toolchain jars/apache from image into the user XDG cache (idempotent).
# Conversation runs as uid 10001 — site-packages tools/ is root-owned; bake avoids Gradle there.
set -eu

BAKE_ROOT="${ONEC_TOOLCHAIN_BAKE:-/opt/1c-dev-cache/1c-dev}"
# Prefer explicit cache; else HOME/.cache (OH sets HOME=/var/openhands/.openhands).
CACHE_ROOT="${XDG_CACHE_HOME:-${HOME:-/tmp}/.cache}/1c-dev"
SRC_TOOLS="${BAKE_ROOT}/tools"
DEST_TOOLS="${CACHE_ROOT}/tools"

if [[ ! -d "$SRC_TOOLS" ]]; then
  printf '[seed-toolchain] no bake at %s — skip\n' "$SRC_TOOLS" >&2
  exit 0
fi

if ! mkdir -p "$DEST_TOOLS" 2>/dev/null; then
  printf '[seed-toolchain] ERROR: cannot write %s (uid=%s). Fix volume ownership (openhands-init).\n' \
    "$DEST_TOOLS" "$(id -u)" >&2
  exit 1
fi

# Prefer rsync when present; otherwise cp missing entries only.
copied=0
if command -v rsync >/dev/null 2>&1; then
  rsync -a --ignore-existing "$SRC_TOOLS"/ "$DEST_TOOLS"/
  copied=1
else
  for item in "$SRC_TOOLS"/*; do
    [[ -e "$item" ]] || continue
    base="$(basename "$item")"
    if [[ ! -e "$DEST_TOOLS/$base" ]]; then
      cp -a "$item" "$DEST_TOOLS/$base"
      copied=$((copied + 1))
    fi
  done
fi

n_jars="$(find "$DEST_TOOLS" -maxdepth 1 -name '*.jar' 2>/dev/null | wc -l | tr -d ' ')"
printf '[seed-toolchain] %s ← %s (jars=%s)\n' "$DEST_TOOLS" "$SRC_TOOLS" "$n_jars" >&2
if [[ "$n_jars" -lt 1 ]]; then
  printf '[seed-toolchain] ERROR: no jars in %s after seed\n' "$DEST_TOOLS" >&2
  exit 1
fi
