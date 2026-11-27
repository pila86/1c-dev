# 1c-agent — OpenHands sandbox

Платформа 1С + EDT/`1cedtcli` + Xvfb/VNC + `1c-dev` + **OpenHands agent-server**, UI — **Agent Canvas**.  
Proposal: [autonomous-agent-sandbox.md](../../docs/proposals/autonomous-agent-sandbox.md).

| Образ | Назначение |
|-------|------------|
| `1c-agent-base:8.5.1-edt2026.2` | платформа + EDT + display + 1c-dev |
| `1c-agent-oh:8.5.1-edt2026.2` | base + OpenHands agent-server (`/health` :8000) |

## Быстрый старт (попробовать OH)

```bash
# 1) дистры (один раз)
mkdir -p distr/onec distr/edt
ln -f ~/Загрузки/server64_8_5_1_1529.zip distr/onec/
ln -f ~/Загрузки/1c_edt_distr_offline_2026.2.2_21_linux_x86_64.tar.gz distr/edt/

# 2) сборка
./docker/agent/build-oh.sh

# 3) конфиг
cp docker/agent/.env.example docker/agent/.env
# HASP_SERVER_ADDR, HTTP_PROXY/HTTPS_PROXY, положить CA в docker/agent/certs/
chmod 777 docker/agent/projects   # uid 10001 (openhands)

# 4) UI
docker compose -f docker/agent/compose.yml --env-file docker/agent/.env up -d
```

Открой **http://127.0.0.1:3000/canvas**  
Conversation runtime = `docker` → контейнеры из `1c-agent-oh:8.5.1-edt2026.2` (1С/EDT/`1c-dev`/VNC).

### Git-репозиторий в workspace (mount, без clone при сборке)

Docker-runtime Canvas использует **isolated workspaces** — в UI нельзя
прикрепить host-папку. Обход:

1. В `.env` укажи существующий checkout: `GIT_REPO_HOST_PATH=/path/to/cib`.
2. Один раз выдай права uid 10001 на коммиты:
   `./docker/agent/scripts/grant-workspace-acl.sh`
3. `scripts/docker-wrapper.sh` при старте conversation монтирует этот путь в
   `/workspace` **RW** — можно `git add` / `git commit` (изменения на хосте).
4. В UI оставляй workspace **default** — репозиторий уже в `/workspace`.

Push в remote скриптами не делается; пуш — только руками на хосте, если нужно.

### Toolchain + sibling MCP (compose stack)

При сборке `1c-agent-base` — `1c-dev toolchain sync` в `/opt/1c-dev-cache`.
Conversation entrypoint только **seed** jars в user cache (uid 10001).

Внешние MCP — **siblings в том же compose** (сеть `1c-agent_default`):

| Service | Settings URL | Примечание |
|---------|--------------|------------|
| `bsl-ls` | `http://127.0.0.1:18767/mcp` | + mount `GIT_REPO_HOST_PATH` → `/workspace` (для `register_workspace_folder`) |
| `v8std-mcp` | `http://127.0.0.1:18766/mcp` | + `v8std-site` (корпус) |
| `mcp-atlassian` | `http://127.0.0.1:18768/mcp` | Jira/Confluence; образ ≡ `uvx mcp-atlassian` |
| bsl-search | profile `mcp-search` | тяжёлый ES; опционально |

Почему `127.0.0.1`, не `http://bsl-ls:…`: Canvas на host network + корп.
`HTTP_PROXY` иначе шлёт Test в Privoxy (503). Conversation в сети стека
поднимает `mcp-local-forward.py` (`127.0.0.1` → DNS sibling).

`docker-wrapper`: `--network 1c-agent_default`. `SKIP_TOOLS_BOOTSTRAP=1`.
Кэш/share: `TOOLCHAIN_CACHE_HOST_DIR`, `TOOLS_SHARE_HOST_DIR`.
`OH_AGENT_HOST_DIR` — абсолютный путь к `docker/agent` (bind entrypoint + `scripts/` с forwarders без rebuild образа).

### MCP в OpenHands Settings (автосид)

`openhands-mcp-bootstrap` → `ensure-mcp-servers.sh`:

- **1c-dev** — stdio в sandbox (`command: 1c-dev`, `args: ["mcp"]`)
- **bsl-language-server** / **v8std** / **mcp-atlassian** — `streamable-http`

**Не** добавляй в UI STDIO `uvx mcp-atlassian` — в conversation sandbox нет `uvx`/creds.
Сиды HTTP заменят запись с тем же ключом `mcp-atlassian`.

UI **Test connection** часто красный (Canvas на host network, без DNS
`bsl-ls` / без бинаря `1c-dev`) — нормально. Нужен **новый** conversation.

`.cursor/mcp.json` Canvas не читает. Ручной повтор:
`./docker/agent/scripts/ensure-mcp-servers.sh`.

### Jira / Confluence (`mcp-atlassian`)

В `docker/agent/.env` (не коммитить токены):

```bash
# Cloud
JIRA_URL=https://your-company.atlassian.net
JIRA_USERNAME=you@company.com
JIRA_API_TOKEN=...

# или Server/DC
# JIRA_URL=https://jira.example.corp
# JIRA_PERSONAL_TOKEN=...
```

Jira часто резолвится **только через** `HTTP_PROXY`/`HTTPS_PROXY` — не добавляй
`jira.*` в `NO_PROXY`. Для Server/DC — `JIRA_PERSONAL_TOKEN`; при MITM-прокси
обычно `JIRA_SSL_VERIFY=false`.

Потом:

```bash
docker compose -f docker/agent/compose.yml --env-file docker/agent/.env up -d mcp-atlassian
docker compose -f docker/agent/compose.yml --env-file docker/agent/.env run --rm openhands-mcp-bootstrap
```

Открой **новый** чат в Canvas и проверь tools Jira.

### LLM (Cognitum / openai-compatible)

В Canvas → **Settings → LLM → Advanced**:

| Поле | Значение |
|------|----------|
| Model | `openai/qwen3.8:27b` (префикс `openai/` обязателен для LiteLLM) |
| Base URL | `https://cognitum.ite.service/api/v1/` |
| API Key | токен Cognitum |
| Reasoning effort | `none` (не `high` — Cognitum его не принимает) |
| Native tool calling | **вкл.** (как в Kilo: OpenAI `tools`/`tool_calls`; иначе OH ждёт prompt-tools и модель «молчит») |

После смены модели / native tools — **новый** conversation.

В образе `1c-agent-oh` для корп. CA выставлено `SSL_VERIFY=False` (как `LLM_VERIFY_SSL=false` в `tests/.env.integration`): иначе LiteLLM/OpenSSL 3 падает на «Basic Constraints … not marked critical».

### Debug sandbox без Canvas

```bash
docker compose -f docker/agent/compose.yml --env-file docker/agent/.env \
  --profile debug up -d sandbox-debug
curl -fsS -H "X-Session-API-Key: $(grep SESSION_API_KEY docker/agent/.env | cut -d= -f2-)" \
  http://127.0.0.1:18000/health
# VNC: localhost:5901 (или VNC_PORT из .env)
```

## Корп. сертификаты

1. **Bake:** `*.crt`/`*.pem` → `docker/agent/certs/` + пересборка base/oh.  
2. **Runtime:** mount хост-каталога в `/certs` (`ORG_CERTS_HOST_DIR`).

Entrypoint: `update-ca-certificates`, `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE` /
`NODE_EXTRA_CA_CERTS`, импорт в Java `cacerts`.

## HTTP(S) прокси

В `.env` или `proxy.env`:

```bash
HTTP_PROXY=http://proxy.example.corp:3128
HTTPS_PROXY=http://proxy.example.corp:3128
NO_PROXY=localhost,127.0.0.1,.example.corp,192.168.0.0/16
```

Нормализация upper/lower, `git` proxy, `JAVA_TOOL_OPTIONS` для `1cedtcli`/jars.

## Сборка по шагам

```bash
docker build -t 1c-agent-base:8.5.1-edt2026.2 -f docker/agent/Dockerfile.base .
docker build -t 1c-agent-oh:8.5.1-edt2026.2 \
  --build-arg BASE_IMAGE=1c-agent-base:8.5.1-edt2026.2 \
  --build-arg OH_AGENT_SERVER_VERSION=1.64.1 \
  -f docker/agent/Dockerfile.openhands docker/agent
```

## Env

| Переменная | Назначение |
|------------|------------|
| `HASP_SERVER_ADDR` | → `nethasp.ini` |
| `ORG_CERTS_HOST_DIR` / `ORG_CERTS_DIR` | CA на хосте / в контейнере (`/certs`) |
| `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY` | прокси в корпсеть |
| `OH_CONVERSATION_RUNTIME` | `docker` — conversation в sandbox-образе |
| `OH_CONVERSATION_IMAGE` | `1c-agent-oh:…` |
| `DOCKER_GID` | GID группы `docker` на хосте (сокет) |
| `VNC_PASSWORD` / `VNC_PORT` | VNC (debug profile; порт по умолчанию 5901) |
| `EDT_JAVA_XMX` | heap `1cedtcli` |
| `GIT_REPO_HOST_PATH` | host checkout → `/workspace` conversation (RW) и `bsl-ls` (RO) |
| `GIT_REPO_URL` / `GIT_BRANCH` | метаданные remote/ветки (опционально) |
| `GIT_AUTHOR_NAME` / `GIT_AUTHOR_EMAIL` | identity для `git commit` в sandbox |
| `MCP_BOOTSTRAP_WAIT_SECS` | таймаут ожидания Canvas API для сида MCP (default 180) |
| `MCP_HTTP_PORT` | только profile `mcp-http` (default 9100) |
| `TOOLCHAIN_CACHE_HOST_DIR` | host cache → conversation `~/.cache/1c-dev` |
| `TOOLS_SHARE_HOST_DIR` | host share → conversation `~/.local/share/1c-dev` |
| `OH_COMPOSE_NETWORK` | сеть стека для conversation (default `1c-agent_default`) |
| `MCP_HTTP_SERVERS` | сид HTTP MCP: `bsl-ls,v8std,atlassian` (опц. `bsl-search`) |
| `OH_AGENT_HOST_DIR` | abs path `docker/agent` → bind entrypoint в conversation |
| `JIRA_URL` / `JIRA_*_TOKEN` | creds sibling `mcp-atlassian` (Cloud или Server/DC) |
| `SKIP_TOOLS_BOOTSTRAP` | default `1` — siblings в compose, не `services up` в sandbox |

## Фазы

| Фаза | Статус |
|------|--------|
| **0** base, doctor, VNC, build/check XML+EDT | done |
| **1** OH agent-server + Agent Canvas compose + MCP example | done (нужен LLM key в UI) |
| **2** volumes toolchain, pin OH, memory 16g, certs/proxy | done |
| **3** issue→PR / Automate очередь | UI Automate есть в Canvas; полный e2e — после LLM/git tokens |

## Проверено

- `1c-agent-oh` → `GET /health` → `{"status":"ok"}`; Xvfb+x11vnc; certs+proxy hooks; `1c-dev`/`ibcmd` в PATH  
- Agent Canvas → http://127.0.0.1:3000/canvas (200); `OH_CONVERSATION_IMAGE=1c-agent-oh:…`; docker.sock OK  
