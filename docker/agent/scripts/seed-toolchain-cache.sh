#!/usr/bin/env bash
# Copy baked toolchain jars/apache from image into the user XDG cache (idempotent).
# Conversation runs as uid 10001 — site-packages tools/ is root-owned; bake avoids Gradle there.
set -eu

BAKE_ROOT="${ONEC_TOOLCHAIN_BAKE:-/opt/1c-dev-cache/1c-dev}"
CACHE_ROOT="${XDG_CACHE_HOME:-${HOME:-/tmp}/.cache}/1c-dev"
SRC_TOOLS="${BAKE_ROOT}/tools"
DEST_TOOLS="${CACHE_ROOT}/tools"

if [[ ! -d "$SRC_TOOLS" ]]; then
  printf '[seed-toolchain] no bake at %s — skip\n' "$SRC_TOOLS" >&2
  exit 0
fi

mkdir -p "$DEST_TOOLS"
# Prefer rsync when present; otherwise cp missing entries only.
if command -v rsync >/dev/null 2>&1; then
  rsync -a --ignore-existing "$SRC_TOOLS"/ "$DEST_TOOLS"/
else
  for item in "$SRC_TOOLS"/*; do
    [[ -e "$item" ]] || continue
    base="$(basename "$item")"
    if [[ ! -e "$DEST_TOOLS/$base" ]]; then
      cp -a "$item" "$DEST_TOOLS/$base"
    fi
  done
fi

printf '[seed-toolchain] %s ← %s\n' "$DEST_TOOLS" "$SRC_TOOLS" >&2
