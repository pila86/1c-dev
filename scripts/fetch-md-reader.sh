#!/usr/bin/env bash
# Build md-reader jar into the local 1c-dev tools cache (ADR-012).
# Requires: JDK 21+ (MDClasses 0.20.0), Gradle 8+
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

pick_java() {
  local candidates=()
  if [[ -n "${JAVA_HOME:-}" ]]; then
    candidates+=("${JAVA_HOME}/bin/java")
  fi
  if command -v java >/dev/null 2>&1; then
    candidates+=("$(command -v java)")
  fi
  # Common Linux JDK 21 installs when PATH still points at older java
  for home in \
    /usr/lib/jvm/java-21-openjdk-amd64 \
    /usr/lib/jvm/java-1.21.0-openjdk-amd64 \
    /usr/lib/jvm/temurin-21-jdk-amd64 \
    /usr/lib/jvm/zulu-21*
  do
    if [[ -x "${home}/bin/java" ]]; then
      candidates+=("${home}/bin/java")
    fi
  done

  local bin major
  for bin in "${candidates[@]}"; do
    [[ -x "${bin}" ]] || continue
    major="$("${bin}" -version 2>&1 | sed -n 's/.*version "\([0-9]*\).*/\1/p' | head -1)"
    [[ -n "${major}" ]] || continue
    if [[ "${major}" -ge 21 ]]; then
      echo "${bin}"
      return 0
    fi
  done
  return 1
}

JAVA_BIN="$(pick_java || true)"
if [[ -z "${JAVA_BIN}" ]]; then
  echo "ERROR: Java 21+ required for md-reader / MDClasses (set JAVA_HOME or install JDK 21)" >&2
  exit 1
fi
export JAVA_HOME="$(cd "$(dirname "${JAVA_BIN}")/.." && pwd)"

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

echo "Building md-reader (${PIN}) with Java ${JAVA_HOME}..."
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
