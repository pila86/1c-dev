#!/usr/bin/env bash
# Build pinned xml-gen jar into the local 1c-dev tools cache (ADR-007).
set -euo pipefail

REPO_URL="https://github.com/SteelMorgan/1c-agent-based-dev-framework.git"
COMMIT="19f67bfed6d15f051f9568678bab1701b7735f95"
SHORT="${COMMIT:0:12}"

if [[ -n "${XDG_CACHE_HOME:-}" ]]; then
  CACHE_DIR="${XDG_CACHE_HOME}/1c-dev/tools"
else
  CACHE_DIR="${HOME}/.cache/1c-dev/tools"
fi
PINNED_JAR="${CACHE_DIR}/xml-gen-${SHORT}.jar"
STABLE_JAR="${CACHE_DIR}/xml-gen.jar"

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
  echo "xml-gen already built: ${STABLE_JAR}"
  exit 0
fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/1c-dev-xmlgen.XXXXXX")"
cleanup() { rm -rf "${WORK}"; }
trap cleanup EXIT

echo "Cloning xml-gen @ ${SHORT}..."
git clone --filter=blob:none --sparse "${REPO_URL}" "${WORK}/src"
git -C "${WORK}/src" sparse-checkout set tools/xml-gen
git -C "${WORK}/src" checkout "${COMMIT}"

echo "Building xml-gen..."
(
  cd "${WORK}/src/tools/xml-gen"
  chmod +x ./gradlew
  ./gradlew build -x test --no-daemon -q
)

BUILT="$(ls "${WORK}/src/tools/xml-gen/build/libs"/xml-gen-*.jar | head -1)"
if [[ -z "${BUILT}" || ! -f "${BUILT}" ]]; then
  echo "ERROR: built jar not found" >&2
  exit 1
fi

cp -f "${BUILT}" "${PINNED_JAR}"
cp -f "${PINNED_JAR}" "${STABLE_JAR}"
echo "Installed: ${STABLE_JAR}"
