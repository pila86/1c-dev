# ADR-033: External Tools Manager

**Статус:** Accepted  
**Дата:** 2026-11-19

## Контекст

1c-dev — CLI проекта 1С (`init`, `publish`, `runtime`, …). Нужна подсистема для
сторонних локальных инструментов разработки (MCP/сервисы): каталог recipes →
установка → lifecycle → проводка в IDE MCP.

Сейчас `1c-dev tools` = только toolchain jars (ADR-013). Смешивать jars и
user-scoped Docker MCP нельзя: разные layout, lifecycle и семантика `clean`.

Spike: [external-tools-manager](../spikes/external-tools-manager.md).  
Первый vertical slice (Этап 1): [zeegin/v8std](https://github.com/zeegin/v8std).  
Issue: [#172](https://github.com/pila86/1c-dev/issues/172).

## Решение

### 1. Toolchain ≠ external tools

| Подсистема | CLI | Хранение |
|------------|-----|----------|
| Toolchain (jars/apache/yaxunit) | `toolchain sync\|clean` | cache (`~/.cache/1c-dev/tools/`) |
| External tools (MCP/сервисы) | `tools list\|info\|install\|update\|remove` | share (`~/.local/share/1c-dev/tools/<id>/`) |
| Managed services | `services up\|down\|restart\|status\|logs` | share + docker; state later |

Миграция naming:

- Канон: `1c-dev toolchain sync|clean`.
- Alias: `1c-dev tools sync|clean` ≥ 1 minor (help/deprecate note); warning — later.
- `tools` без sync/clean — только external tools.

`toolchain clean` **не** удаляет installed external tools, service state и data volumes.

### 2. Install ≠ run

`tools install` материализует recipe в share и делает pull образов.
`services up` поднимает stack. `init` не ставит global tools и не делает `up`.

### 3. Local managed HTTP — основной путь

Для v8std / будущих MCP: `lifecycle: managed`, Streamable HTTP на loopback.
`external` URL — escape hatch, не MVP-драйвер Этапа 1.

### 4. Docker/compose — один runtime adapter (не центр вселенной)

Этап 1: тонкая обёртка compose **только под v8std**. Универсальный Service Manager —
Этап 2. Process/stdio adapters — позже по необходимости.

### 5. Services управляют только external tools

`publish` / `runtime` **не** входят в Service Manager (ADR-019 / ADR-025).

### 6. `init` остаётся project-only

Global tools / `services up` — отдельные команды, не wizard внутри `init`.

### 7. IDE — consumer конфигурации

`ide configure` пишет/мержит MCP и guidance (ADR-016). Не автозапускает сервисы.
При unreachable HTTP — warning + suggestion `services up` (polish — Этап 4; в Этапе 1 —
doctor/status).

### 8. Recipes в monorepo (`catalog/`)

Корень SoT: **`catalog/<id>/`**, не top-level `tools/` (Java toolchain).
Адаптация tool = содержимое каталога, не отдельный repo на каждый tool.

```text
catalog/<id>/
  tool.yaml
  compose.yaml          # overlay / pin
  env.default
  agent/guidance.md
```

Поток: `catalog/<id>/` → `tools install` → `~/.local/share/1c-dev/tools/<id>/`
(копия recipe + пользовательский `.env`).

### 9. State/data не в cache

```text
~/.config/1c-dev/           # config.yaml, tools.yaml (preferences; later)
~/.local/share/1c-dev/
  tools/<id>/               # installed recipe + .env
  services/state.json       # Этап 2; Этап 1 — минимальный status из compose
  data/<id>/                # volumes / dumps
~/.cache/1c-dev/            # toolchain + downloads (можно чистить)
```

Windows share: `%LOCALAPPDATA%\1c-dev\share\tools\<id>\` (аналог XDG_DATA_HOME).
Cache остаётся как ADR-013.

### 10. Сначала локально

Remote / marketplace / systemd user units — вне scope до отдельного ADR.

### 11. Agent guidance обязателен для optional MCP UX

Optional MCP без when/when-not не считается готовым UX.
Guidance условный: только если tool installed (и/или в desire-list — Этап 5).
При `tools remove` / отсутствии tool — `ide configure` **убирает** managed guidance.

Каналы Этапа 1 (should):

| Канал | Маркер |
|-------|--------|
| Секция в `AGENTS.md` | `<!-- BEGIN 1c-dev:v8std -->` … `<!-- END 1c-dev:v8std -->` |
| Managed IDE rule | `ext-v8std-when-to-use` (`managedBy: 1c-dev`) |

Приоритет: v8std — SoT по стандартам разработки 1С; локальные rules
(`bsl-module-structure`, …) дополняют / не дублируют корпус стандартов.
Must-поток (`docs.*`, bsl-ls, metadata/build/check/test) не заменяется v8std.

### Schema `tool.yaml` (Этап 1)

```yaml
id: v8std
name: 1C Development Standards (v8std)
version: "0.1.0"          # версия recipe
mcp_name: v8std           # ключ в mcpServers

scope: user
lifecycle: managed

source:
  type: docker

runtime:
  type: compose
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

### v8std defaults (Этап 1)

| Параметр | Значение |
|----------|----------|
| Site port | `18765` |
| MCP port | `18766` |
| Images | `ghcr.io/zeegin/v8std-site:sha-58fff9f7cce57e98c884e01eded360236cfa47ee`, `ghcr.io/zeegin/v8std-mcp:sha-58fff9f7cce57e98c884e01eded360236cfa47ee` |
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
core/tools/          catalog loader, installer, registry
core/services/       thin compose wrapper (v8std → Этап 2 generalization)
core/mcp/            опционально позже; Этап 1 — формирование url в ide.py
catalog/             shipped recipes
```

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| External = `addons` CLI | без rename tools | два словаря; tools остаётся двусмысленным | Отвергнуто |
| Repo-per-tool | изоляция | overhead без image/data-plane | Отложено |
| Только remote URL MCP | проще | нет local-first / offline site | Отвергнуто для MVP |
| Смешать с toolchain cache | меньше путей | clean ломает сервисы; разные lifecycle | Отвергнуто |
| `init` ставит global tools | «одна кнопка» | ломает project-only init | Отвергнуто |

## Последствия

- Реализовать Этап 1 (#172): catalog v8std, tools/services CLI, ide + doctor.
- Обновить CONTRIBUTING: `toolchain sync` + alias.
- Расширить ADR-013 note: share layout; `toolchain clean` границы.
- Этапы 2–6 — отдельные issues после стабильного v8std slice.

## Связанные решения

- [ADR-010](010-mcp-architecture.md) — MCP stdio; HTTP url — расширение consumer side
- [ADR-013](013-packaging-toolchain-cache.md) — toolchain cache; share — здесь
- [ADR-016](016-ide-configure.md) — merge mcp.json / AGENTS / rules
- [ADR-019](019-runtime-client-lifecycle.md) / [ADR-025](025-publish-backends.md) — не смешивать
- Spike [external-tools-manager](../spikes/external-tools-manager.md)
- Issue [#172](https://github.com/pila86/1c-dev/issues/172)
