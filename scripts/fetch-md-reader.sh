#!/usr/bin/env bash
# Build md-reader jar into the local 1c-dev tools cache (ADR-012).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${ROOT}/tools/md-reader"
VERSION="0.1.0"
PIN="mdclasses-0.20.0"

if [[ -n "${XDG_CACHE_HOME:-}" ]]; then
  CACHE_DIR="${XDG_CACHE_HOME}/1c-dev/tools"
else
  CACHE_DIR="${HOME}/.cache/1c-dev/tools"
fi
PINNED_JAR="${CACHE_DIR}/md-reader-${PIN}.jar"
STABLE_JAR="${CACHE_DIR}/md-reader.jar"

if [[ -n "${JAVA_HOME:-}" ]]; then
  JAVA_BIN="${JAVA_HOME}/bin/java"
else
  JAVA_BIN="$(command -v java || true)"
fi
if [[ -z "${JAVA_BIN}" || ! -x "${JAVA_BIN}" ]]; then
  echo "ERROR: Java 17+ required (set JAVA_HOME or add java to PATH)" >&2
  exit 1
fi

MAJOR="$("${JAVA_BIN}" -version 2>&1 | sed -n 's/.*version "\([0-9]*\).*/\1/p' | head -1)"
if [[ -z "${MAJOR}" ]]; then
  echo "ERROR: cannot parse java -version" >&2
  exit 1
fi
if [[ "${MAJOR}" -lt 17 ]]; then
  echo "ERROR: Java 17+ required (found major ${MAJOR})" >&2
  exit 1
fi

mkdir -p "${CACHE_DIR}"
if [[ -f "${PINNED_JAR}" ]]; then
  cp -f "${PINNED_JAR}" "${STABLE_JAR}"
  echo "md-reader already built: ${STABLE_JAR}"
  exit 0
fi

GRADLE_BIN="$(command -v gradle || true)"
if [[ -z "${GRADLE_BIN}" ]]; then
  # Prefer a cached Gradle distribution if present
  for candidate in \
    "${HOME}/.gradle/wrapper/dists"/gradle-8.*/**/gradle-8.*/bin/gradle
  do
    if [[ -x "${candidate}" ]]; then
      GRADLE_BIN="${candidate}"
      break
    fi
  done
fi
if [[ -z "${GRADLE_BIN}" ]]; then
  echo "ERROR: gradle not found (install Gradle 8+ or ensure wrapper dists exist)" >&2
  exit 1
fi

echo "Building md-reader (${PIN})..."
(
  cd "${SRC}"
  "${GRADLE_BIN}" fatJar --no-daemon -q
)

BUILT="${SRC}/build/libs/md-reader.jar"
if [[ ! -f "${BUILT}" ]]; then
  echo "ERROR: built jar not found at ${BUILT}" >&2
  exit 1
fi

cp -f "${BUILT}" "${PINNED_JAR}"
cp -f "${PINNED_JAR}" "${STABLE_JAR}"
echo "Installed: ${STABLE_JAR}"
