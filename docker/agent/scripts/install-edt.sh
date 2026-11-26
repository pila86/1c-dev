#!/usr/bin/env bash
# Silent install of 1C:EDT / 1cedtcli from distr/edt offline archive.
set -euo pipefail

DIST_DIR="${1:-/tmp/edt-dist}"

if [[ ! -d "$DIST_DIR" ]]; then
  echo "ERROR: EDT distr not found: $DIST_DIR" >&2
  exit 1
fi

work="$(mktemp -d /tmp/edt-install.XXXXXX)"
cleanup() { rm -rf "$work"; }
trap cleanup EXIT

shopt -s nullglob
for archive in "$DIST_DIR"/*.{tar.gz,tgz,zip}; do
  case "$archive" in
    *.tar.gz|*.tgz) tar -xzf "$archive" -C "$work" ;;
    *.zip) unzip -q "$archive" -d "$work" ;;
  esac
done
# Already extracted tree
if [[ -z "$(ls -A "$work" 2>/dev/null || true)" ]]; then
  cp -a "$DIST_DIR"/. "$work"/
fi

cd "$work"

installer="$(find . -maxdepth 3 -type f -name '1ce-installer-cli' | head -n1 || true)"
if [[ -z "$installer" ]]; then
  # Offline EDT packs often ship car/dar + lib/; launch via java -jar style wrapper if present.
  if [[ -f ./1ce-installer-cli ]]; then
    installer=./1ce-installer-cli
  else
    echo "ERROR: 1ce-installer-cli not found in EDT distr" >&2
    find . -maxdepth 2 -type f | head -50 >&2
    exit 1
  fi
fi

chmod +x "$installer"
echo "Installing EDT via $installer"
"$installer" install all --ignore-hardware-checks --ignore-signature-warnings

# Symlinks expected by PATH / doctor
ring_dir="$(dirname "$(find /opt/1C/1CE -type f -name ring 2>/dev/null | head -n1 || true)" || true)"
edtcli_bin="$(find /opt/1C/1CE -type f -name 1cedtcli 2>/dev/null | head -n1 || true)"

mkdir -p /opt/1C/1CE/components
if [[ -n "$ring_dir" ]]; then
  ln -sfn "$ring_dir" /opt/1C/1CE/components/1c-enterprise-ring
fi
if [[ -n "$edtcli_bin" ]]; then
  ln -sfn "$(dirname "$edtcli_bin")" /opt/1C/1CE/components/1cedtcli
fi
if [[ ! -f /etc/1C/1CE/ring-commands.cfg ]]; then
  mkdir -p /etc/1C/1CE
  touch /etc/1C/1CE/ring-commands.cfg
fi

if [[ -z "$edtcli_bin" ]]; then
  echo "ERROR: 1cedtcli not found after EDT install" >&2
  exit 1
fi
echo "EDT installed: $edtcli_bin"
