#!/usr/bin/env bash
# Silent install of 1C platform from distr/onec (setup-full .run or .deb).
set -euo pipefail

DIST_DIR="${1:-/tmp/onec-dist}"
INSTALLER_TYPE="${INSTALLER_TYPE:-client}" # server | client (client = server+client_full)

if [[ ! -d "$DIST_DIR" ]]; then
  echo "ERROR: platform distr not found: $DIST_DIR" >&2
  exit 1
fi

work="$(mktemp -d /tmp/onec-install.XXXXXX)"
cleanup() { rm -rf "$work"; }
trap cleanup EXIT

# Unpack archives into $work
shopt -s nullglob
for archive in "$DIST_DIR"/*.{zip,tar.gz,tgz}; do
  case "$archive" in
    *.zip) unzip -q "$archive" -d "$work" ;;
    *.tar.gz|*.tgz) tar -xzf "$archive" -C "$work" ;;
  esac
done
# Also accept already-extracted .run / .deb dropped into distr/
cp -a "$DIST_DIR"/. "$work"/ 2>/dev/null || true

cd "$work"

# Prefer .run (setup-full) — covers server + thick client in one shot.
run_file="$(find . -maxdepth 2 -type f -name 'setup-full-*.run' -o -name '*.run' | head -n1 || true)"
if [[ -n "$run_file" ]]; then
  chmod +x "$run_file"
  case "$INSTALLER_TYPE" in
    server) components="server,ws,ru" ;;
    *)      components="server,client_full,ru" ;;
  esac
  echo "Installing platform from $run_file ($components)"
  ./"$run_file" --mode unattended --enable-components "$components"
elif ls ./*.deb >/dev/null 2>&1 || ls ./**/*.deb >/dev/null 2>&1; then
  echo "Installing platform from .deb packages"
  # shellcheck disable=SC2086
  find . -name '1c-enterprise-*-common_*.deb' -print0 | xargs -0 -r dpkg -i
  find . -name '1c-enterprise-*-server_*.deb' -print0 | xargs -0 -r dpkg -i
  find . -name '1c-enterprise-*-client_*.deb' -print0 | xargs -0 -r dpkg -i
else
  echo "ERROR: no setup-full .run or .deb found under $DIST_DIR" >&2
  ls -la "$work" >&2 || true
  exit 1
fi

# Symlink /opt/1cv8/current → version dir (relative target).
ibcmd="$(find /opt/1cv8 -type f -name ibcmd 2>/dev/null | sort -V | tail -n1 || true)"
if [[ -z "$ibcmd" ]]; then
  echo "ERROR: ibcmd not found after install" >&2
  exit 1
fi
onec_home="$(dirname "$(readlink -f "$ibcmd")")"
version="$(basename "$onec_home")"
mkdir -p /opt/1cv8
ln -sfn "x86_64/${version}" /opt/1cv8/current
echo "Platform installed: /opt/1cv8/current -> x86_64/${version}"
test -x /opt/1cv8/current/ibcmd
