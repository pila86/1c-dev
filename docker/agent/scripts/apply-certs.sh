#!/usr/bin/env bash
# Install org CA certificates from ORG_CERTS_DIR into system + Java + Node/Python trust.
set -euo pipefail

ORG_CERTS_DIR="${ORG_CERTS_DIR:-/certs}"
_certs_log() { printf '[agent-certs] %s\n' "$*"; }

if [[ ! -d "$ORG_CERTS_DIR" ]]; then
  _certs_log "ORG_CERTS_DIR=$ORG_CERTS_DIR missing — skip"
  return 0 2>/dev/null || exit 0
fi

shopt -s nullglob
certs=("$ORG_CERTS_DIR"/*.{crt,pem,cer,CERT,PEM,CER})
if [[ ${#certs[@]} -eq 0 ]]; then
  # also accept files without extension / nested
  mapfile -t certs < <(find "$ORG_CERTS_DIR" -type f \( \
      -name '*.crt' -o -name '*.pem' -o -name '*.cer' -o -name '*.CERT' -o -name '*.PEM' \
    \) 2>/dev/null || true)
fi
if [[ ${#certs[@]} -eq 0 ]]; then
  _certs_log "no cert files under $ORG_CERTS_DIR — skip"
  return 0 2>/dev/null || exit 0
fi

dest=/usr/local/share/ca-certificates/1c-agent-org
mkdir -p "$dest"
n=0
for src in "${certs[@]}"; do
  base="$(basename "$src")"
  # update-ca-certificates expects .crt
  case "$base" in
    *.crt|*.CRT) out="$dest/$base" ;;
    *) out="$dest/${base%.*}.crt" ;;
  esac
  cp -f "$src" "$out"
  n=$((n + 1))
done

if command -v update-ca-certificates >/dev/null 2>&1; then
  update-ca-certificates >/tmp/update-ca-certificates.log 2>&1 || {
    _certs_log "update-ca-certificates failed (see /tmp/update-ca-certificates.log)"
  }
else
  _certs_log "update-ca-certificates not found"
fi

# Point common TLS stacks at the system bundle (includes our CAs after update).
bundle=/etc/ssl/certs/ca-certificates.crt
if [[ -f "$bundle" ]]; then
  export SSL_CERT_FILE="$bundle"
  export REQUESTS_CA_BUNDLE="$bundle"
  export CURL_CA_BUNDLE="$bundle"
  export NODE_EXTRA_CA_CERTS="$bundle"
  # Persist for child shells / later processes started from this env file.
  cat >/etc/1c-agent/certs.env <<EOF
export SSL_CERT_FILE=$bundle
export REQUESTS_CA_BUNDLE=$bundle
export CURL_CA_BUNDLE=$bundle
export NODE_EXTRA_CA_CERTS=$bundle
EOF
fi

# Import into Java cacerts (JDK used by 1c-dev toolchain). Soft-fail per cert.
java_home="${JAVA_HOME:-/usr/lib/jvm/java-25-openjdk-amd64}"
cacerts="$java_home/lib/security/cacerts"
if [[ -f "$cacerts" ]] && command -v keytool >/dev/null 2>&1; then
  i=0
  for src in "${certs[@]}"; do
    alias="1c-agent-org-$i"
    keytool -importcert -noprompt -alias "$alias" -file "$src" \
      -keystore "$cacerts" -storepass changeit \
      >/tmp/keytool-import.log 2>&1 || true
    i=$((i + 1))
  done
  _certs_log "Java truststore: attempted import of $i cert(s) into $cacerts"
fi

_certs_log "installed $n org certificate(s) from $ORG_CERTS_DIR"
