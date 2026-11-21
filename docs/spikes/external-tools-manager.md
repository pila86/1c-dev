# Spike: External Tools Manager (локальные MCP/сервисы)

**Статус:** Accepted (ADR-033); Этап 0–1 — done ([#172](https://github.com/pila86/1c-dev/issues/172)); Этапы 2–4 — done ([#175](https://github.com/pila86/1c-dev/issues/175)); Этапы 5+7 — done ([#177](https://github.com/pila86/1c-dev/issues/177)); Этап 6 — deferred  

**Дата:** 2026-11-19  
**Контекст:** переосмысление CLI вокруг сторонних инструментов разработки;
локальный запуск `v8std`, `mcp-bsl-search` и (позже) `bsl-ls` как user-scoped сервисов.
**Связано:** [ADR-033](../adr/033-external-tools-manager.md), ADR-013 (toolchain cache),
ADR-016 (ide configure merge), ADR-010 (MCP stdio), ADR-025 (publish — не смешивать).

## TL;DR

1c-dev остаётся CLI проекта 1С (`init`, `publish`, `runtime`, …), но
добавляет подсистему **External Tools**: каталог → установка recipe →
lifecycle сервисов → проводка в IDE MCP.

- `toolchain` (jars/apache/yaxunit) и **external tools** — разные подсистемы.
- `install ≠ up`: установка не запускает сервис.
- Local-first: Streamable HTTP на loopback, один экземпляр на машину.
- Адаптация tool = **recipe в monorepo** (не отдельный repo на каждый tool).
- `mcp.json` + **agent guidance** (when/when-not): иначе агент не использует optional MCP.
- `publish` / `runtime` не входят в Service Manager.

Первые граждане: [zeegin/v8std](https://github.com/zeegin/v8std),
[axel-avb/mcp-bsl-search](https://github.com/axel-avb/mcp-bsl-search).

## Brief для исполнителя (сеньор / агент в новом чате)

Этот spike — достаточный вход. История обсуждений не нужна.

### Сделать

1. **Этап 0:** ADR External Tools Manager → **Accepted**.
   Закрыть open questions с «Блокирует код? = Да» (naming, ports,
   MCP scope, pin образов). Зафиксировать schema `tool.yaml` и XDG share.
2. **Issue/epic Этапа 1** с must/should, diagnostics codes, acceptance checklist
   (см. §«Этап 1»).
3. **Реализовать только Этап 1** — vertical slice `v8std`:
   - `catalog/v8std/` (`tool.yaml`, compose, `env.default`, `agent/guidance.md`);
   - `tools install/remove/list/info` (+ rename/alias `toolchain sync`);
   - `services up/down/status/logs` как тонкая обёртка compose под v8std;
   - `ide configure`: mcpServers url + should upsert guidance;
   - `doctor` / status: Docker, port, health.
4. Следовать CONTRIBUTING, ADR-016 merge, паттернам CLI / diagnostics / JSON output.

### Не делать в этом поручении

- Этапы 2–7 «заодно» (универсальный Service Manager, bsl-search, desire-list,
  full stack, миграция bsl-ls).
- Marketplace / systemd / remote management.
- Ломать `publish` / `runtime` / семантику `init`.
- Класть recipes в top-level `tools/` (это Java toolchain).

### Definition of Done (Этап 1)

См. checklist в §«Этап 1». Минимум: `install` → `up` → healthy → `ide configure`
видит MCP; (should) guidance появляется только когда tool подключен.

Остальной документ — контекст и детали для ADR/issue. Scope поручения —
только этот Brief + Handoff gate.

## Цели

- Единый UX: посмотреть / установить / поднять / подключить к IDE сторонний tool.
- Не размножать тяжёлые MCP в каждом git-проекте.
- Не превращать `1c-dev init` в global setup wizard.
- Не ломать `tools sync` / `tools clean` (toolchain) без явной миграции.

## Не-цели (сейчас)

- Marketplace / удалённый менеджмент / systemd user units.
- Универсальный менеджер всех процессов 1c-dev (включая publish/runtime).
- Repo-адаптер на каждый upstream tool.
- Полноценный offline full-stack `bsl-search` (ES + embeddings) в MVP.

## Разделение подсистем

| Подсистема | Ответственность | CLI (эскиз) |
|---|---|---|
| Project | init / scope / ide artifacts | `init`, `ide configure` |
| Toolchain | pin jars и soft-deps 1c-dev | `toolchain sync/clean` (alias: `tools sync`) |
| External tools | catalog, install, update, remove | `tools list/info/install/…` |
| Services | up/down/restart/status/logs/health | `services …` |
| MCP/IDE | генерация mcpServers, merge ADR-016 | `ide configure` |
| Runtime / Publish | клиент 1С / публикация ИБ | без изменений |

### Naming

Сейчас `1c-dev tools` = только toolchain. Целевое:

- `1c-dev toolchain sync|clean` — внутренние зависимости;
- `1c-dev tools …` — внешние инструменты;
- на переход: `tools sync` → alias/deprecated на `toolchain sync`.

Альтернатива (если breaking дорогой): внешние = `addons`. Предпочтение —
миграция имени `toolchain`.

## Модель tool

В recipe раздельно:

| Понятие | Смысл |
|---|---|
| Source | Откуда взять (docker image, git, local, remote url) |
| Runtime | Как запускать (compose / docker / process) |
| Interface | MCP Streamable HTTP / stdio / прочее |
| Lifecycle | `managed` \| `client-stdio` \| `external` |
| Healthcheck | HTTP/TCP/command |
| Scope | user (default для local MCP) \| project desire |
| Agent | optional routing для агента (when / when-not), не копия знаний MCP |

Local-first: основной путь — `lifecycle: managed` + compose stack.
`external` (готовый URL) — escape hatch, не MVP-драйвер.

### Recipes в monorepo

Корень каталога — **`catalog/`**, не `tools/`: существующий top-level `tools/`
занят Java toolchain (`md-reader`, `docs-facade`) и не смешивается с external MCP.

```text
catalog/                      # SoT shipped recipes (в wheel / git)
  v8std/
    tool.yaml
    compose.yaml              # overlay / pin upstream images
    env.default
    agent/
      guidance.md             # when / when-not для агента
    scripts/                  # опционально; исключение, не основной путь
  bsl-search/
    tool.yaml
    compose.app.yaml          # mcp-server + search-api
    env.default
    agent/
      guidance.md
    scripts/                  # preflight / restore-index (если нужно)
    # compose.full.yaml       # later: + ES (+ inference)
  bsl-ls/                     # Этап 7: shared MCP (streamable HTTP)
    tool.yaml
    env.default               # pin jar / port / java
    agent/
      guidance.md
    # runtime: process (jar) предпочтительнее compose
```

Контракт: **Tool Recipe**. Адаптация = содержимое каталога, не форк upstream.
Логика `install`/`up` — в Python (`core/tools`, `core/services`); shell в
`scripts/` — только то, что неудобно выразить декларативно.

Поток:

```text
catalog/<id>/  --tools install-->  ~/.local/share/1c-dev/tools/<id>/
                                   (копия recipe + пользовательский .env)
                 --services up-->  docker compose / process
```

Отдельный git-repo на tool — только если появится свой image/data-plane/команда.

## Хранение (XDG)

```text
~/.config/1c-dev/           # config.yaml, tools.yaml (user preferences)
~/.local/share/1c-dev/
  tools/<id>/               # installed recipe materialization, .env
  services/state.json
  data/<id>/                # volumes / dumps (не кэш)
~/.cache/1c-dev/            # toolchain + downloads (можно чистить)
```

`toolchain clean` не удаляет installed tools, service state и data volumes.
ADR-013 (cache-only) расширяется для share — отдельным ADR.

## Целевые tools

### v8std (первый vertical slice)

- Upstream: Docker site + MCP, Streamable HTTP, healthz.
- Self-contained; один user-scoped stack.
- UX: `tools install v8std` → `services up v8std` → `ide configure`.
- Endpoint на `127.0.0.1` (стабильный default port).

### bsl-search (вторым, профили)

Upstream compose поднимает только app; ES / embedding / reranker — внешние.
Индекс большой (~13GB+), полный embed — часы.

| Профиль | 1c-dev поднимает | Пользователь даёт |
|---|---|---|
| `app` (MVP) | mcp-server + search-api | `ELASTICSEARCH_URL`, inference URLs |
| `full` (later) | app + ES (+ optional inference) | диск/RAM; restore dump |

Не обещать «одной кнопкой полный RAG» в первом релизе.

### bsl-ls / bsl-language-server (миграция с toolchain)

Сейчас: jar в toolchain cache + **stdio MCP на каждый проект**
(`java -jar … mcp` в `.cursor`/`.kilo` mcp.json, ADR-016). Тяжёлый JVM
процесс размножается по открытым workspace.

Цель: **один user-scoped инстанс** на машину → `tools install` /
`services up` → `ide configure` пишет общий Streamable HTTP endpoint;
проекты регистрируют корни через `register_workspace_folder` (уже в AGENTS).

Upstream уже умеет (док [McpMode](https://1c-syntax.github.io/bsl-language-server/features/McpMode/)):

```text
java -jar bsl-language-server.jar mcp --protocol streamable --server.port=<port>
```

Версия (на 2026-11-21):

| Кандидат | Статус | Заметки |
|---|---|---|
| `1.0.7` | последний **stable** | без MCP tools `register_workspace_folder` (нужны Cursor) |
| `1.1.0-rc.4` | **текущий pin** toolchain | [#4462](https://github.com/1c-syntax/bsl-language-server/pull/4462): MCP workspace folders вместо roots |
| `1.1.0-rc.9` | последний RC | линия 1.1.0; stable `1.1.0` ещё нет |

«Взять последний stable» = откат на `1.0.7` и потеря must-фичи для Cursor.
Политика для этапа: **остаться на линии 1.1.0-rc**, bump до свежего RC
(или до `1.1.0`, когда выйдет); откат на 1.0.x — только с явным решением.

## CLI (целевой)

| Команда | Назначение |
|---|---|
| `toolchain sync\|clean` | Бывший tools sync/clean |
| `tools list\|info\|install\|update\|remove` | External tools |
| `services up\|down\|restart\|status\|logs` | Managed stacks |
| `ide configure` | Merge MCP (stdio + HTTP url), без авто-up |
| `doctor` / `status` | Включить external tools + health сервисов |

`init` не устанавливает global tools и не делает `services up`.

Позже (не MVP): `.1c-dev/tools.yaml` — desire-list проекта для воспроизводимости.

## Архитектура кода (эскиз)

```text
core/tools/          catalog loader, manifest, installer, registry, source adapters
core/services/       manager, state, health, compose/docker/process adapters
core/mcp/            формирование MCP-конфигов (stdio / streamable-http)
catalog/             shipped recipes (не путать с top-level tools/ — Java toolchain)
```

Примитивы PID/docker labels по возможности переиспользовать идеи из
`runtime`/`publish`, **без** слияния доменов.

## Этапы реализации

### Этап 0 — ADR + naming

- ADR External Tools Manager.
- Решение по rename `tools sync` → `toolchain sync` (+ alias).
- Layout share vs cache; границы `clean`.

### Этап 1 — Vertical slice: v8std

Минимальный путь end-to-end. Compose-адаптер **только под v8std**
(не универсальный Service Manager).

- Формат `tool.yaml` + recipe `catalog/v8std/`.
- `tools install/remove/list/info`.
- `services up/down/status/logs` — тонкая обёртка над `docker compose`
  для одного stack id.
- `ide configure` пишет HTTP MCP server (merge ADR-016).
- **Should:** upsert минимального `agent/guidance.md` для v8std (см. § Agent guidance).
- `doctor`: Docker, port, health endpoint.

Acceptance (черновик checklist — зафиксировать в issue):

- [x] `catalog/` попадает в wheel / editable install
- [x] `1c-dev tools install v8std` материализует recipe в share + pull images
- [x] `1c-dev services up v8std` идемпотентен; health ok
- [x] `1c-dev ide configure` добавляет mcpServers.v8std с url (чужие ключи не трогает)
- [x] (should) `ide configure` ставит managed guidance v8std; без tool — секции нет
- [x] `1c-dev doctor` / `services status` показывают reachable/unreachable
- [x] JSON output + diagnostics codes для fail-путей
- [x] Linux must; Windows — should (Docker Desktop) или явный skip + diagnostic

### Этап 2 — Обобщение Service Manager

Вынести из v8std-специфики:

- [x] Stack-level API (project name, env file, health, idempotent up).
- [x] State в `~/.local/share/1c-dev/services/`.
- [x] Labels `managed-by=1c-dev`.
- [x] Готовность принять второй recipe (`bsl-search`) без копипасты.

### Этап 3 — bsl-search (local BM25 stack)

Решения (#175): build app из git; ES в том же compose; при install скачать
`units_curated.jsonl` с HF; BM25 сейчас; `EMBEDDING_URL`/`RERANKER_URL` — later.

- [x] Recipe `catalog/bsl-search/` (compose ES+app build, env, guidance, README).
- [x] `tools install`: git clone upstream + HF download + normalize JSONL.
- [x] `services up`: compose `--build`, bulk-load в ES (idempotent; `BSL_SEARCH_REINDEX=1`).
- [x] Optional inference via `.env` (пустые по умолчанию).
- [ ] Knowledge ITS/Habr auto-index (later).
- [ ] Precomputed embeddings / kNN dump (later / Этап 6).

### Этап 4 — MCP/IDE polish

- [x] Проверка unreachable endpoint → warning + suggestion `services up`.
- [x] Сохранение чужих mcpServers (ADR-016).
- [x] Общий upsert/remove agent guidance по installed tools.
- [x] Опционально `external` URL.
- [ ] Desire-list sync guidance (Этап 5).

### Этап 5 — Project desire-list

Решения (#177): список required tool id в `.1c-dev/tools.yaml`;
`tools check` (installed/healthy); `ide configure` учитывает desire для
guidance; **не** трогать `init`; **не** авто-`install`/`up`.

- [x] Schema `.1c-dev/tools.yaml` + loader
- [x] `1c-dev tools check` (+ JSON / diagnostics)
- [x] `ide configure`: guidance = installed ∪ desire; MCP url — только installed
- [x] Тесты; docs

### Этап 6 (optional) — bsl-search `full`

- ES volume, restore dump, optional inference.
- Только после стабильного `app` профиля.

### Этап 7 — bsl-ls как shared External Tool

Перевести `bsl-language-server` с per-project stdio (toolchain + ADR-016)
на каталог External Tools / Services: **один инстанс на машину**, к которому
ходят несколько проектов.

Must:

- [x] Recipe `catalog/bsl-ls/` (`tool.yaml`, runtime process, `env.default`,
      `agent/guidance.md` — when/when-not vs `docs.*`).
- [x] `lifecycle: managed` + Streamable HTTP
      (`mcp --protocol streamable --server.port=…` на loopback).
- [x] `tools install bsl-ls` — jar (github-release) в share;
      `services up/down/status/logs` + health.
- [x] `ide configure`: mcpServers.url (как v8std/bsl-search), **не** stdio
      `java -jar` на каждый проект; чужие ключи не трогать (ADR-016).
- [x] Multi-project: агент регистрирует корень через `register_workspace_folder`
      (уже в templates AGENTS); один процесс держит несколько workspace folders.
- [x] Pin **`1.1.0-rc.9`** (+ sha256) в recipe — решение #177 (не `1.0.7`).
- [x] Миграция с toolchain: jar **убран** из `toolchain sync` / stdio ADR-016;
      без stdio fallback при down (только warning `services up`).
- [x] `doctor`: installed bsl-ls / health; diagnostics codes.

Should:

- [x] Default port `18767` + конфликт → error + suggestion (как v8std).
- [x] Process adapter: jar + JVM без Docker.
- [x] Override `ONEC_BSLLS_JAR` сохраняется.
- [x] Guidance: shared instance ≠ «свой LS на проект»; не unregister чужие folders.

Acceptance (черновик):

- [x] `tools install bsl-ls` → `services up bsl-ls` → health ok на loopback
- [x] Два разных ide-root после `ide configure` указывают на **один** URL
- [ ] В каждом проекте `register_workspace_folder` + lookup/`analyze_file` работают
      (manual / live)
- [x] Без `services up` — warning unreachable + suggestion (Этап 4)
- [x] Pin версии задокументирован в recipe/`env.default` (+ sha256)

Не в этом этапе: LSP-режим редактора (только MCP-агентский путь);
marketplace; systemd user unit (можно later как runtime adapter).

## Главные решения (зафиксировать в ADR)

1. Toolchain ≠ external tools.
2. Install ≠ run.
3. Local managed HTTP — основной путь для v8std / bsl-search / (Этап 7) bsl-ls.
4. Docker/compose — один runtime adapter, не центр вселенной.
5. Services управляют только external tools.
6. `init` остаётся project-only.
7. IDE — consumer конфигурации, не менеджер сервисов.
8. Recipes в monorepo; не repo-per-tool без доказанной тяжести.
9. State/data не в cache.
10. Сначала локально; remote/marketplace — позже.
11. Optional MCP без agent guidance не считается готовым UX; guidance условный (только если tool подключен).

## Открытые вопросы

| Вопрос | Предложение для Этапа 1 (закрыть в ADR) | Блокирует код? |
|---|---|---|
| Default ports v8std | Host: site `18765`, MCP via proxy `18766` (как upstream compose); конфликт порта → error + suggestion | Да |
| MCP config scope | Только project `.cursor`/`.kilo` mcp.json (как ADR-016); user-global — later | Да |
| Pin образов v8std | Tag **или** digest в `env.default`; SoT — maintainers 1c-dev; без pin — не merge | Да |
| Alias `tools sync` | Сразу `toolchain sync` + alias `tools sync` ≥ 1 minor; warning later | Да (naming) |
| Dump индекса bsl-search | Вне Этапа 1; решить к Этапу 3/6 | Нет (пока) |
| Windows | Should: Docker Desktop; иначе diagnostic `ENV_UNAVAILABLE` | Желательно |
| Приоритет v8std vs локальные IDE rules | v8std — SoT по стандартам; local rules дополняют / не дублируют; уточнить в ADR | Желательно (should guidance) |
| Версия bsl-ls | **Закрыто (#177):** pin `1.1.0-rc.9` | — |
| Shared bsl-ls: process vs compose | **Закрыто (#177):** process + jar (без Docker) | — |
| Dual-path stdio при down | **Закрыто (#177):** HTTP + warning `services up`; без stdio fallback | — |
| Jar: toolchain vs catalog only | **Закрыто (#177):** SoT в recipe; убрать из toolchain в том же PR; `ONEC_BSLLS_JAR` override | — |

## Пример recipe: `catalog/v8std/tool.yaml`

Иллюстративный контракт (не финальный schema). Поля и имена уточнить в ADR.

```yaml
id: v8std
name: 1C Development Standards (v8std)
version: "0.1.0"          # версия recipe, не обязательно = tag образа
mcp_name: v8std           # ключ в mcpServers

scope: user
lifecycle: managed

source:
  type: docker
  # конкретные image/tag|digest — в env.default / compose

runtime:
  type: compose
  file: compose.yaml
  project_name: 1c-dev-v8std
  profiles: [mcp]         # если нужен MCP-сервис upstream

interface:
  type: mcp
  transport: streamable-http
  # URL, который попадает в IDE (host loopback)
  url: "http://127.0.0.1:${V8STD_MCP_PORT:-18766}/mcp"

healthcheck:
  type: http
  # уточнить: host proxy vs container healthz
  url: "http://127.0.0.1:${V8STD_MCP_PORT:-18766}/healthz"
  timeout_sec: 2

service:
  enabled: true

agent:
  guidance: agent/guidance.md
  # mode: agents-section | ide-rule | both  (уточнить в ADR)
```

Рядом в recipe:

```text
catalog/v8std/
  tool.yaml
  compose.yaml      # overlay над upstream delivery/local (labels, project)
  env.default       # V8STD_SITE_IMAGE, V8STD_MCP_IMAGE, ports
  agent/
    guidance.md     # when / when-not для агента
  # scripts/        # обычно не нужно для v8std
```

`env.default` (эскиз):

```bash
V8STD_SITE_PORT=18765
V8STD_MCP_PORT=18766
# Заменить на проверенный tag или digest перед релизом recipe:
V8STD_SITE_IMAGE=ghcr.io/zeegin/v8std-site:REPLACE_ME
V8STD_MCP_IMAGE=ghcr.io/zeegin/v8std-mcp:REPLACE_ME
```

## Agent guidance для optional MCP

Подключить endpoint в `mcp.json` недостаточно: агент должен знать,
**когда** звать внешний MCP и **когда не звать** (иначе игнор или шум).

Базовый `templates/configuration/AGENTS.md` остаётся про must-tools
(`1c-dev`, `bsl-language-server`, `docs.*`). Инструкции про optional tools
**не** живут там всегда — только если tool установлен / в desire-list проекта
и попал в `ide configure`.

### Принципы

1. Guidance = routing (when / when-not / приоритет), не копия содержимого MCP.
2. Условность: «если MCP `<mcp_name>` доступен в сессии — …; если нет — не invent
   и не притворяйся, что вызвал tool».
3. Не конфликтовать с must-потоком: metadata / build / check / test / debug /
   `docs.*` / bsl-ls остаются первичными для своих задач.
4. При `tools remove` или исчезновении из desire — `ide configure` **убирает**
   managed guidance (мёртвые «используй v8std» хуже отсутствия).

### Где лежит в recipe

```text
catalog/<id>/
  tool.yaml          # agent.guidance: …
  agent/
    guidance.md      # фрагмент для AGENTS и/или тело IDE rule
```

`ide configure`:

- пишет/мержит MCP server (как ADR-016);
- upsert managed-фрагмента guidance, если tool installed (и/или в
  `.1c-dev/tools.yaml`);
- не автозапускает `services up`; при unreachable HTTP — warning + suggestion.

Каналы (как ADR-016):

| Канал | Для чего |
|---|---|
| Секция в managed `AGENTS.md` (`<!-- BEGIN 1c-dev:<id> -->`) | порядок выбора tools / lifecycle hints |
| Managed IDE rule (`ext-<id>-when-to-use`) | узкий «когда звать» с хорошим description |

### Эскиз содержания guidance

**v8std**

- Когда: стандарты разработки, антипаттерны, «принято ли так в 1С».
- Когда не: вместо `docs.*` / bsl-ls (API платформы); вместо `metadata.*` /
  build / check / test.
- Приоритет: уточнить в ADR vs локальные rules (`bsl-module-structure`, …) —
  предложение: v8std SoT по стандартам, local rules дополняют.

**bsl-search**

- Когда: поиск похожих реализаций / паттернов в корпусе; не выдумывать код с нуля.
- Когда не: вместо чтения текущего workspace; вместо точного API lookup;
  не execute BSL.

### Привязка к этапам

- Этап 1 (v8std): must — mcp.json; **should** — минимальный `agent/guidance.md`
  + upsert при `ide configure`.
- Этап 4: общий механизм remove/upsert, unreachable hint, desire-list sync.
- Этап 3 (bsl-search): свой `agent/guidance.md` в recipe.

## Handoff gate

### Кому можно отдавать этот spike сейчас

| Аудитория | Можно? |
|---|---|
| Review направления / согласование | Да |
| Сеньор / агент по §«Brief для исполнителя» (ADR → issue → Этап 1) | **Да** |
| Исполнитель «только код», без права закрывать ADR | **Нет**, пока не закрыт gate ниже |

### До кода Этапа 1 закрыть

(Сеньор/агент по Brief закрывает это сам в рамках поручения.)

1. **Spike согласован** (этот документ или правки).
2. **ADR External Tools Manager — Accepted** (решения из §«Главные решения» + naming + XDG share).
3. **Issue/epic Этапа 1** с must/should, diagnostics codes, acceptance checklist.
4. Закрыты open questions, помеченные «Блокирует код? = Да».
5. В issue зафиксированы: schema `tool.yaml` (или ссылка на ADR), default ports, pin образов v8std, политика Windows.
6. Явно: Этап 1 = v8std-only compose wrapper; обобщение — Этап 2.

### Не передавать как ТЗ на код

- «Реализуйте весь spike / этапы 1–7» (игнорировать Brief).
- «Сделайте bsl-search full stack» до стабильного `app` и отдельного issue.
- «Мигрируйте bsl-ls на shared HTTP» без отдельного issue Этапа 7 и решения по версии.

## Следующий шаг

1. Согласовать этот spike (в т.ч. Brief).
2. Отдать исполнителю с отсылкой на §«Brief для исполнителя».
3. ~~Строка в `docs/roadmap.md`~~ — уже есть в таблице Spikes.
