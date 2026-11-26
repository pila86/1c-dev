#!/usr/bin/env bash
# Normalize HTTP(S) proxy env for curl/git/pip/java/node.
# Accepts HTTP_PROXY/HTTPS_PROXY/NO_PROXY (and lowercase) or /etc/1c-agent/proxy.env.
set -euo pipefail

_proxy_log() { printf '[agent-proxy] %s\n' "$*"; }

mkdir -p /etc/1c-agent

if [[ -f /etc/1c-agent/proxy.env ]]; then
  # shellcheck disable=SC1091
  set -a
  # shellcheck disable=SC1091
  source /etc/1c-agent/proxy.env
  set +a
  _proxy_log "loaded /etc/1c-agent/proxy.env"
fi

# Prefer uppercase; mirror to lowercase for tools that only read one form.
if [[ -n "${HTTP_PROXY:-${http_proxy:-}}" ]]; then
  export HTTP_PROXY="${HTTP_PROXY:-$http_proxy}"
  export http_proxy="$HTTP_PROXY"
fi
if [[ -n "${HTTPS_PROXY:-${https_proxy:-}}" ]]; then
  export HTTPS_PROXY="${HTTPS_PROXY:-$https_proxy}"
  export https_proxy="$HTTPS_PROXY"
elif [[ -n "${HTTP_PROXY:-}" ]]; then
  # Many corp setups use one proxy for both.
  export HTTPS_PROXY="$HTTP_PROXY"
  export https_proxy="$HTTP_PROXY"
fi
if [[ -n "${NO_PROXY:-${no_proxy:-}}" ]]; then
  export NO_PROXY="${NO_PROXY:-$no_proxy}"
  export no_proxy="$NO_PROXY"
else
  # Sensible defaults so localhost / HASP LAN calls aren't proxied by accident.
  export NO_PROXY="localhost,127.0.0.1,::1,.local"
  export no_proxy="$NO_PROXY"
fi

if [[ -z "${HTTP_PROXY:-}" && -z "${HTTPS_PROXY:-}" ]]; then
  _proxy_log "no HTTP(S)_PROXY set — skip"
  return 0 2>/dev/null || exit 0
fi

# Persist for login shells / later exec without losing exports.
cat >/etc/1c-agent/proxy.env.runtime <<EOF
export HTTP_PROXY='${HTTP_PROXY:-}'
export HTTPS_PROXY='${HTTPS_PROXY:-}'
export NO_PROXY='${NO_PROXY:-}'
export http_proxy='${http_proxy:-}'
export https_proxy='${https_proxy:-}'
export no_proxy='${no_proxy:-}'
EOF

# Git (system config needs root; fall back to --global for non-root / OH conversations)
if command -v git >/dev/null 2>&1; then
  _git_proxy() {
    local key="$1" val="$2"
    git config --system "$key" "$val" 2>/dev/null \
      || git config --global "$key" "$val" 2>/dev/null \
      || true
  }
  [[ -n "${HTTP_PROXY:-}" ]] && _git_proxy http.proxy "$HTTP_PROXY"
  [[ -n "${HTTPS_PROXY:-}" ]] && _git_proxy https.proxy "$HTTPS_PROXY"
fi
# Do not leak `set -e` into callers that source this file.
set +e


# Java (1cedtcli / toolchain jars) — only append if not already present.
if [[ -n "${HTTP_PROXY:-}${HTTPS_PROXY:-}" ]]; then
  parse_proxy() {
    # http://user:pass@host:port → host/port (naive; enough for corp proxies)
    local url="$1"
    local no_scheme="${url#*://}"
    local hostport="${no_scheme##@}"
    hostport="${hostport%%/*}"
    if [[ "$hostport" == *:* ]]; then
      echo "${hostport%:*}" "${hostport##*:}"
    else
      echo "$hostport" "8080"
    fi
  }
  java_opts="${JAVA_TOOL_OPTIONS:-}"
  if [[ -n "${HTTP_PROXY:-}" ]]; then
    read -r ph pp < <(parse_proxy "$HTTP_PROXY")
    java_opts+=" -Dhttp.proxyHost=${ph} -Dhttp.proxyPort=${pp}"
  fi
  if [[ -n "${HTTPS_PROXY:-}" ]]; then
    read -r ph pp < <(parse_proxy "$HTTPS_PROXY")
    java_opts+=" -Dhttps.proxyHost=${ph} -Dhttps.proxyPort=${pp}"
  fi
  if [[ -n "${NO_PROXY:-}" ]]; then
    # Java wants | -separated nonProxyHosts with *.domain
    np="$(echo "$NO_PROXY" | tr ',' '|' | sed 's/\./\\./g; s/\*/.*/g')"
    java_opts+=" -Dhttp.nonProxyHosts=${np}"
  fi
  export JAVA_TOOL_OPTIONS="${java_opts# }"
  echo "export JAVA_TOOL_OPTIONS='${JAVA_TOOL_OPTIONS}'" >>/etc/1c-agent/proxy.env.runtime
fi

_proxy_log "proxy active HTTP_PROXY=${HTTP_PROXY:-} HTTPS_PROXY=${HTTPS_PROXY:-} NO_PROXY=${NO_PROXY:-}"
