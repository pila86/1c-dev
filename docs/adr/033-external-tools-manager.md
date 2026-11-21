# ADR-033: External Tools Manager

**Статус:** Accepted  
**Дата:** 2026-11-19  
**Обновлено:** 2026-11-21 (этапы 0–5, 7 done; этап 6 deferred)

## Контекст

1c-dev — CLI проекта 1С (`init`, `publish`, `runtime`, …). Нужна подсистема для
сторонних локальных инструментов разработки (MCP/сервисы): каталог recipes →
установка → lifecycle → проводка в IDE MCP.

Сейчас `1c-dev tools` = только toolchain jars (ADR-013). Смешивать jars и
user-scoped Docker MCP нельзя: разные layout, lifecycle и семантика `clean`.

Первый vertical slice: [zeegin/v8std](https://github.com/zeegin/v8std).  
Реализация: [#172](https://github.com/pila86/1c-dev/issues/172) (этап 1),
[#175](https://github.com/pila86/1c-dev/issues/175) (этапы 2–4),
[#177](https://github.com/pila86/1c-dev/issues/177) (этапы 5+7).

## Решение

### 1. Toolchain ≠ external tools

| Подсистема | CLI | Хранение |
|------------|-----|----------|
| Toolchain (jars/apache/yaxunit) | `toolchain sync\|clean` | cache (`~/.cache/1c-dev/tools/`) |
| External tools (MCP/сервисы) | `tools list\|info\|install\|update\|remove\|check` | share (`~/.local/share/1c-dev/tools/<id>/`) |
| Managed services | `services up\|down\|restart\|status\|logs` | share + docker/process; state в share |

Миграция naming:

- Канон: `1c-dev toolchain sync|clean`.
- Alias: `1c-dev tools sync|clean` ≥ 1 minor (help/deprecate note); warning — later.
- `tools` без sync/clean — только external tools.

`toolchain clean` **не** удаляет installed external tools, service state и data volumes.

### 2. Install ≠ run

`tools install` материализует recipe в share (pull images / download jar / clone).
`services up` поднимает stack. `init` не ставит global tools и не делает `up`.

### 3. Local managed HTTP — основной путь

Для v8std / bsl-search / bsl-ls: `lifecycle: managed`, Streamable HTTP на loopback.
`external` URL — escape hatch.

### 4. Runtime adapters: compose и process

Service Manager обобщён (этап 2): stack-level API, state в
`~/.local/share/1c-dev/services/`, labels `managed-by=1c-dev`.

| Adapter | Tools |
|---------|-------|
| `compose` | v8std, bsl-search |
| `process` | bsl-ls (jar + JVM, без Docker) |

stdio как managed lifecycle — не используется для shared MCP; project stdio
остаётся только у `1c-dev` (ADR-016).

### 5. Services управляют только external tools

`publish` / `runtime` **не** входят в Service Manager (ADR-019 / ADR-025).

### 6. `init` остаётся project-only

Global tools / `services up` — отдельные команды, не wizard внутри `init`.

### 7. IDE — consumer конфигурации

`ide configure` пишет/мержит MCP и guidance (ADR-016). Не автозапускает сервисы.
При unreachable HTTP — warning + suggestion `services up`.

### 8. Recipes в monorepo (`catalog/`)

Корень SoT: **`catalog/<id>/`**, не top-level `tools/` (Java toolchain).
Адаптация tool = содержимое каталога, не отдельный repo на каждый tool.

```text
catalog/<id>/
  tool.yaml
  compose.yaml          # optional; для compose runtime
  env.default
  agent/guidance.md
```

Поток: `catalog/<id>/` → `tools install` → `~/.local/share/1c-dev/tools/<id>/`
(копия recipe + пользовательский `.env`).

Shipped: `v8std`, `bsl-search`, `bsl-ls`.

### 9. State/data не в cache

```text
~/.config/1c-dev/           # config.yaml, user preferences
~/.local/share/1c-dev/
  tools/<id>/               # installed recipe + .env
  services/state.json
  data/<id>/                # volumes / dumps / process runtime (pid, logs)
~/.cache/1c-dev/            # toolchain + downloads (можно чистить)
```

Windows share: `%LOCALAPPDATA%\1c-dev\share\tools\<id>\` (аналог XDG_DATA_HOME).
Cache остаётся как ADR-013.

### 10. Сначала локально

Remote / marketplace / systemd user units — вне scope до отдельного ADR.

### 11. Agent guidance обязателен для optional MCP UX

Optional MCP без when/when-not не считается готовым UX.
Guidance: `installed ∪ desire-list`. MCP url в `mcp.json` — только для installed.
При `tools remove` / отсутствии в desire — `ide configure` **убирает** managed guidance.

Каналы:

| Канал | Маркер |
|-------|--------|
| Секция в `AGENTS.md` | `<!-- BEGIN 1c-dev:<id> -->` … `<!-- END 1c-dev:<id> -->` |
| Managed IDE rule | `ext-<id>-when-to-use` (`managedBy: 1c-dev`) |

Приоритет: v8std — SoT по стандартам разработки 1С; локальные rules
(`bsl-module-structure`, …) дополняют / не дублируют корпус стандартов.
Must-поток (`docs.*`, bsl-ls, metadata/build/check/test) не заменяется v8std.

### 12. Project desire-list

Файл проекта `.1c-dev/tools.yaml` — список required tool id (воспроизводимость
ожиданий, не auto-setup).

- `1c-dev tools check` — catalog / installed / healthy; JSON + diagnostics.
- `init` **не** создаёт и не синхронизирует desire-list.
- Нет auto-`install` / auto-`up`.

### 13. bsl-search: профили `app` (done) и `full` (deferred)

| Профиль | Статус | 1c-dev поднимает | Пользователь даёт |
|---------|--------|------------------|-------------------|
| `app` | done (#175) | ES + search-api + mcp-server; BM25 из HF `units_curated.jsonl` | optional `EMBEDDING_URL` / `RERANKER_URL` |
| `full` | deferred | + restore dump / embeddings / kNN / optional inference in-compose | диск/RAM |

Не обещать «одной кнопкой полный RAG». Knowledge ITS/Habr auto-index — later.

### 14. bsl-ls: shared External Tool (не toolchain)

Один user-scoped инстанс на машину; несколько проектов → один Streamable HTTP URL.

| Решение | Значение |
|---------|----------|
| Pin | `1.1.0-rc.9` (+ sha256 в recipe); не stable `1.0.7` (нет `register_workspace_folder`) |
| Runtime | `process` + jar (`github-release`), не Docker |
| MCP | upstream native: `java -jar … mcp --protocol streamable --server.port=…` |
| Default port | `18767` |
| Toolchain | jar **убран** из `toolchain sync` / per-project stdio |
| Service down | HTTP url + warning `services up`; **без** stdio fallback |
| Override | `ONEC_BSLLS_JAR` сохраняется |
| Multi-project | `register_workspace_folder` (AGENTS); не unregister чужие folders |

LSP-режим редактора — вне этого ADR (только MCP-агентский путь).

### Schema `tool.yaml` (контракт)

```yaml
id: v8std
name: 1C Development Standards (v8std)
version: "0.1.0"          # версия recipe
mcp_name: v8std           # ключ в mcpServers

scope: user
lifecycle: managed

source:
  type: docker            # docker | git | github-release | …

runtime:
  type: compose           # compose | process
  file: compose.yaml
  project_name: 1c-dev-v8std
  profiles: [mcp]

interface:
  type: mcp
  transport: streamable-http
  url: "http://127.0.0.1:${V8STD_MCP_PORT:-18766}/mcp"

healthcheck:
  type: http
  url: "http://127.0.0.1:${V8STD_MCP_PORT:-18766}/healthz"
  timeout_sec: 2

service:
  enabled: true

agent:
  guidance: agent/guidance.md
  mode: both                 # agents-section + ide-rule
```

### v8std defaults

| Параметр | Значение |
|----------|----------|
| Site port | `18765` |
| MCP port | `18766` |
| Images | pin tag/digest в `catalog/v8std/env.default` |
| Compose | site + mcp, `docker compose --profile mcp` |
| MCP scope | project `.cursor` / `.kilo` mcp.json only |
| Windows | should: Docker Desktop; иначе diagnostic + `ENV_UNAVAILABLE` |

Конфликт порта → error + suggestion сменить порт в `.env` / освободить порт.
Pin образов — SoT maintainers 1c-dev в `env.default`; без pin — не merge recipe.

### Diagnostics (префикс `1CX`)

| Code | Ситуация |
|------|----------|
| `1CX001` | tool id не найден в catalog |
| `1CX002` | tool уже установлен / не установлен |
| `1CX003` | Docker / compose недоступен |
| `1CX004` | порт занят |
| `1CX005` | health unreachable |
| `1CX006` | pull / compose failure |
| `1CX007` | recipe / env pin отсутствует |

Exit codes — ADR-003 (`ENV_UNAVAILABLE` / `RUNTIME_FAILURE` по ситуации).

### Архитектура кода

```text
core/tools/          catalog, install, desire-list, github-release, …
core/services/       manager + compose / process adapters, state, health
core/project/ide.py  mcpServers (stdio 1c-dev + HTTP installed tools) + guidance
catalog/             shipped recipes (v8std, bsl-search, bsl-ls)
```

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| External = `addons` CLI | без rename tools | два словаря; tools остаётся двусмысленным | Отвергнуто |
| Repo-per-tool | изоляция | overhead без image/data-plane | Отложено |
| Только remote URL MCP | проще | нет local-first / offline site | Отвергнуто для MVP |
| Смешать с toolchain cache | меньше путей | clean ломает сервисы; разные lifecycle | Отвергнуто |
| `init` ставит global tools | «одна кнопка» | ломает project-only init | Отвергнуто |
| bsl-ls per-project stdio | привычный ADR-016 | N JVM на N workspace | Отвергнуто (#177) |
| bsl-ls stable 1.0.7 | «не RC» | нет MCP workspace folders для Cursor | Отвергнуто (#177) |
| Dual-path stdio при down | «всегда есть LS» | размножение процессов; два контракта | Отвергнуто (#177) |

## Последствия

| Этап | Статус | Issue |
|------|--------|-------|
| 0 ADR + naming | done | ADR-033 |
| 1 Vertical slice v8std | done | [#172](https://github.com/pila86/1c-dev/issues/172) |
| 2 Service Manager | done | [#175](https://github.com/pila86/1c-dev/issues/175) |
| 3 bsl-search `app` (BM25) | done | [#175](https://github.com/pila86/1c-dev/issues/175) |
| 4 MCP/IDE polish | done | [#175](https://github.com/pila86/1c-dev/issues/175) |
| 5 Project desire-list | done | [#177](https://github.com/pila86/1c-dev/issues/177) |
| 6 bsl-search `full` | **deferred** | отдельный issue при необходимости |
| 7 Shared bsl-ls | done | [#177](https://github.com/pila86/1c-dev/issues/177) |

UX и CLI: см. CONTRIBUTING (`tools` / `services` / desire-list / `bsl-ls`).

## Связанные решения

- [ADR-010](010-mcp-architecture.md) — MCP stdio; HTTP url — расширение consumer side
- [ADR-013](013-packaging-toolchain-cache.md) — toolchain cache; share — здесь
- [ADR-016](016-ide-configure.md) — merge mcp.json / AGENTS / rules; bsl-ls HTTP
- [ADR-019](019-runtime-client-lifecycle.md) / [ADR-025](025-publish-backends.md) — не смешивать
- Issues [#172](https://github.com/pila86/1c-dev/issues/172),
  [#175](https://github.com/pila86/1c-dev/issues/175),
  [#177](https://github.com/pila86/1c-dev/issues/177)
