#!/usr/bin/env bash
# Build pinned Apache httpd into the local 1c-dev tools cache (ADR-013 / #94).
# Official ASF sources: httpd + apr + apr-util → user-owned prefix (no sudo).
set -euo pipefail

HTTPD_VER="${ONEC_HTTPD_VER:-2.4.68}"
APR_VER="${ONEC_APR_VER:-1.7.6}"
APU_VER="${ONEC_APU_VER:-1.6.5}"

HTTPD_URL="${ONEC_HTTPD_URL:-https://downloads.apache.org/httpd/httpd-${HTTPD_VER}.tar.gz}"
APR_URL="${ONEC_APR_URL:-https://downloads.apache.org/apr/apr-${APR_VER}.tar.gz}"
APU_URL="${ONEC_APU_URL:-https://downloads.apache.org/apr/apr-util-${APU_VER}.tar.gz}"

if [[ -n "${XDG_CACHE_HOME:-}" ]]; then
  CACHE_DIR="${XDG_CACHE_HOME}/1c-dev/tools"
else
  CACHE_DIR="${HOME}/.cache/1c-dev/tools"
fi
PIN="${HTTPD_VER}"
PREFIX="${CACHE_DIR}/apache"
PINNED="${CACHE_DIR}/apache-${PIN}"
BUILD="${TMPDIR:-/tmp}/1c-dev-httpd-build-$$"

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERROR: нужен $1 в PATH" >&2
    exit 1
  fi
}

need_cmd curl
need_cmd tar
need_cmd make
need_cmd gcc

if ! pkg-config --exists libpcre2-8 2>/dev/null \
  && [[ ! -f /usr/include/pcre2.h ]] \
  && [[ ! -f /usr/local/include/pcre2.h ]]; then
  echo "ERROR: нужен PCRE2 (Ubuntu: sudo apt-get install -y libpcre2-dev)" >&2
  exit 1
fi

mkdir -p "${CACHE_DIR}" "${BUILD}"
cleanup() {
  rm -rf "${BUILD}"
}
trap cleanup EXIT

echo "→ download httpd ${HTTPD_VER} / apr ${APR_VER} / apr-util ${APU_VER}"
curl -fsSL -o "${BUILD}/httpd.tar.gz" "${HTTPD_URL}"
curl -fsSL -o "${BUILD}/apr.tar.gz" "${APR_URL}"
curl -fsSL -o "${BUILD}/apu.tar.gz" "${APU_URL}"

echo "→ unpack"
tar xzf "${BUILD}/httpd.tar.gz" -C "${BUILD}"
tar xzf "${BUILD}/apr.tar.gz" -C "${BUILD}"
tar xzf "${BUILD}/apu.tar.gz" -C "${BUILD}"

SRC="${BUILD}/httpd-${HTTPD_VER}"
mv "${BUILD}/apr-${APR_VER}" "${SRC}/srclib/apr"
mv "${BUILD}/apr-util-${APU_VER}" "${SRC}/srclib/apr-util"

echo "→ configure --prefix=${PREFIX}"
cd "${SRC}"
./configure \
  --prefix="${PREFIX}" \
  --enable-mpms-shared=all \
  --enable-mods-shared=most \
  --with-included-apr

echo "→ make -j$(nproc)"
make -j"$(nproc)"

echo "→ install"
rm -rf "${PREFIX}" "${PINNED}"
make install

# Stable + pinned copies (как jars в tools/).
cp -a "${PREFIX}" "${PINNED}"

MACHINE="$(uname -m | tr '[:upper:]' '[:lower:]')"
case "$(uname -s)" in
  Linux) OS=linux ;;
  Darwin) OS=darwin ;;
  *) OS="$(uname -s | tr '[:upper:]' '[:lower:]')" ;;
esac
case "${MACHINE}" in
  x86_64|amd64) ARCH=x86_64 ;;
  aarch64|arm64) ARCH=aarch64 ;;
  *) ARCH="${MACHINE}" ;;
esac
PLATFORM_KEY="${OS}_${ARCH}"

# Meta для resolve_apache_home / fetch_apache.
cat > "${PREFIX}/.1c-dev-apache.json" <<EOF
{
  "modules_dir": "${PREFIX}/modules",
  "binary": "${PREFIX}/bin/httpd",
  "platform": "${PLATFORM_KEY}",
  "source": "asf-source",
  "httpd": "${HTTPD_VER}",
  "apr": "${APR_VER}",
  "apr_util": "${APU_VER}"
}
EOF
cp -f "${PREFIX}/.1c-dev-apache.json" "${PINNED}/.1c-dev-apache.json"

"${PREFIX}/bin/httpd" -v
echo "✓ apache home: ${PREFIX}"
echo "  modules: ${PREFIX}/modules"
echo "  pin: ${PINNED}"
