# 1c-agent — OpenHands sandbox

Платформа 1С + EDT/`1cedtcli` + Xvfb/VNC + `1c-dev` + **OpenHands agent-server**, UI — **Agent Canvas**.  
Proposal: [autonomous-agent-sandbox.md](../../docs/proposals/autonomous-agent-sandbox.md).

| Образ | Назначение |
|-------|------------|
| `1c-agent-base:8.5.1-edt2026.2` | платформа + EDT + display + 1c-dev |
| `1c-agent-oh:8.5.1-edt2026.2` | base + OpenHands agent-server (`/health` :8000) |

## Запуск

```bash
# 1) дистры (один раз)
mkdir -p distr/onec distr/edt
# положить zip платформы и tarball EDT

# 2) сборка
./docker/agent/build-oh.sh

# 3) конфиг
cp docker/agent/.env.example docker/agent/.env
# обязательное: HASP_SERVER_ADDR, GIT_REPO_HOST_PATH, OH_AGENT_HOST_DIR,
#   LLM_BASE_URL + LLM_API_KEY, proxy/certs при необходимости
chmod 777 docker/agent/projects   # uid 10001
./docker/agent/scripts/grant-workspace-acl.sh   # ACL на checkout для коммитов

# 4) стек
docker compose -f docker/agent/compose.yml --env-file docker/agent/.env up -d
```

Открой **http://127.0.0.1:3000/canvas** и **новый** чат.

Данные Canvas — `/home/openhands/.openhands` (путь одинаковый на хосте и в контейнере; `openhands-init` сам chown 10001).  
Сброс: `docker compose run --rm openhands-init` не нужен отдельно — просто  
`docker run --rm -v /home/openhands/.openhands:/data alpine sh -c 'rm -rf /data/* /data/.[!.]*'`  
и снова `docker compose up -d` (init починит права).

При старте `openhands-bootstrap` один раз пишет в Settings: LLM provider/profile и MCP.  
Повтор: `docker compose … run --rm openhands-bootstrap`.

## Что в compose, а что нет

```text
compose up
  ├─ openhands (Canvas, host network, docker.sock)
  ├─ bsl-ls / v8std-* / mcp-atlassian   ← sibling MCP
  ├─ openhands-bootstrap               ← сид LLM + MCP в Settings
  └─ (chat) Canvas → docker run 1c-agent-oh
         ↑
         docker-wrapper подменяет CLI и добавляет mounts/сеть
```

**Чат не описан как service** — его стартует Canvas. Обход ограничений UI (isolated workspace, нет host-folder):  
[`scripts/docker-wrapper.sh`](scripts/docker-wrapper.sh) смонтирован как `/usr/local/bin/docker` и при `docker run …1c-agent-oh…` добавляет:

| Inject | Откуда |
|--------|--------|
| `/workspace` RW | `GIT_REPO_HOST_PATH` → `OH_INJECT_GIT_REPO_HOST_PATH` |
| toolchain cache / tools share | `TOOLCHAIN_*` / `TOOLS_SHARE_*` |
| `--network` | `OH_COMPOSE_NETWORK` (DNS → `bsl-ls`, …) |
| entrypoint + scripts | `OH_AGENT_HOST_DIR` (без rebuild образа) |
| MCP forwarder env | `MCP_LOCAL_FORWARD=1` |

В conversation `mcp-local-forward.py` слушает `127.0.0.1:1876x` и проксирует на sibling по DNS — те же URL, что в Settings (`http://127.0.0.1:…/mcp`), работают и для Canvas Test, и в чате.

Отладка **без** Canvas (всё видно в compose):

```bash
docker compose -f docker/agent/compose.yml --env-file docker/agent/.env \
  --profile debug up -d sandbox-debug
curl -fsS -H "X-Session-API-Key: $(grep SESSION_API_KEY docker/agent/.env | cut -d= -f2-)" \
  http://127.0.0.1:18000/health
# VNC: localhost:5901
```

## LLM

В `.env` (не коммитить ключи и корп. хосты):

```bash
LLM_PROVIDER_NAME=local-openai
LLM_PROVIDER=openai
LLM_BASE_URL=https://llm.example.corp/api/v1/
LLM_API_KEY=...
LLM_MODEL=openai/qwen3.8:27b
LLM_PROFILE_NAME=local-qwen
LLM_NATIVE_TOOL_CALLING=true
LLM_REASONING_EFFORT=none
```

Префикс `openai/` в модели обязателен для LiteLLM. После смены профиля — новый чат.

## MCP

| Service | Settings URL | Примечание |
|---------|--------------|------------|
| `bsl-ls` | `http://127.0.0.1:${BSLLS_MCP_PORT}/mcp` (default 18767) | + mount repo → `/workspace` |
| `v8std-mcp` | `http://127.0.0.1:${V8STD_MCP_PORT}/mcp` (default 18766) | + `v8std-site` |
| `mcp-atlassian` | `http://127.0.0.1:${MCP_ATLASSIAN_PORT}/mcp` (default 18768) | Jira/Confluence |
| `1c-dev` | stdio `1c-dev mcp` | внутри conversation |

UI **Test connection** для stdio часто красный (в Canvas нет бинаря `1c-dev`) — нормально.  
Не добавляй в UI STDIO `uvx mcp-atlassian` — в sandbox нет `uvx`/creds.

Jira: в `.env` `JIRA_*`; hostname часто только через `HTTP_PROXY` — не клади jira.* в `NO_PROXY`.

## Корп. CA и прокси

1. `*.crt`/`*.pem` → `docker/agent/certs/` (+ rebuild) или mount `ORG_CERTS_HOST_DIR`.
2. `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY` в `.env` (в `NO_PROXY` — loopback, HASP IP, DNS sibling’ов).

## Сборка по шагам

```bash
docker build -t 1c-agent-base:8.5.1-edt2026.2 -f docker/agent/Dockerfile.base .
docker build -t 1c-agent-oh:8.5.1-edt2026.2 \
  --build-arg BASE_IMAGE=1c-agent-base:8.5.1-edt2026.2 \
  --build-arg OH_AGENT_SERVER_VERSION=1.64.1 \
  -f docker/agent/Dockerfile.openhands docker/agent
```

## Env (кратко)

| Переменная | Назначение |
|------------|------------|
| `HASP_SERVER_ADDR` | → `nethasp.ini` |
| `GIT_REPO_HOST_PATH` | host checkout → `/workspace` |
| `OH_AGENT_HOST_DIR` | abs path `docker/agent` для bind entrypoint/scripts |
| `OH_COMPOSE_NETWORK` | сеть стека для conversation |
| `LLM_*` | сид provider + profile |
| `MCP_*` / `JIRA_*` | sibling MCP |
| `TOOLCHAIN_CACHE_HOST_DIR` / `TOOLS_SHARE_HOST_DIR` | кэш между чатами |
| `DOCKER_GID` | GID `docker` на хосте |
