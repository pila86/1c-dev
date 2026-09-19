# M3: source formats (EDT + CF import)

## Goal

Единый agent/CLI API для работы с конфигурацией независимо от source format (XML и EDT), плюс онбординг существующей конфигурации из артефакта `.cf` в project source без ручного Конфигуратора.

## Prerequisites

- M1 зелёный (init → metadata.create → build → check)
- M2: Metadata API (list/get/find + update / create beyond Catalog) по существующему source
- Платформа 1С 8.3.x, `ibcmd` в PATH
- Для EDT-ветки: `1cedtcli` (или согласованный EDT CLI) в окружении

## Scope

### 1. EDT adapter

- Source Adapter для EDT рядом с XML
- `source.convert` XML ↔ EDT без смены agent-level API
- `build` / `check` / `metadata.*` работают одинаково при `source.format: edt`

### 2. Import из `.cf` (CF → source)

Bootstrap / онбординг: бинарный `.cf` → file IB → выгрузка в `source.path` (сначала XML; EDT — через convert).

`.cf` — **входной** артефакт (не source of truth). Дальше истина — Git + source format проекта.

Pipeline (ibcmd):

```text
create IB (если нет)
  → config load <file.cf>
  → config apply
  → config export → source.path
  → [опционально] source.convert --to=edt
```

Публичный контракт (не через `build`):

```bash
1c-dev project import --from configuration.cf
# MCP: project.import
```

Опционально узкий platform-шаг (только CF → IB, без dump в source):

```bash
1c-dev runtime load --from configuration.cf
# MCP: runtime.load
```

Конфликты с уже изменённым `src/` — явный `--force` / отказ с structured diagnostic.

## Agent workflows

### A. Существующий `.cf` → работа через metadata API

> Импортируй configuration.cf в проект и покажи список справочников.

```
1. project.import(from=configuration.cf)
2. metadata.list / metadata.find
3. build / check (по необходимости)
```

### B. Переключение формата

> Переведи проект на EDT и проверь сборку.

```
1. source.convert(to=edt)
2. build
3. check
```

## Acceptance criteria

- [ ] EDT Source Adapter: detect / read path совместим с Metadata API (M2)
- [ ] `1c-dev source convert --to=edt` и `--to=xml` меняют `source.format` и содержимое source
- [ ] После convert тот же MCP flow (`metadata.*`, `build`, `check`) без смены tool names
- [ ] `1c-dev project import --from <file.cf>` создаёт/обновляет XML source и валидный `1c.project.yaml`
- [ ] После import `metadata.list` / `get` видят объекты из `.cf`
- [ ] `build` и `check` после import проходят (или дают платформенные diagnostics)
- [ ] Конфликт с dirty source без `--force` → ошибка с diagnostic, source не затёрт
- [ ] MCP: `project.import` (и при наличии scope — `runtime.load`, `source.convert`) без shell.exec
- [ ] Integration-тесты: skip с сообщением, если нет platform / EDT CLI
- [ ] Contract tests Source Adapter: XML и EDT на общем наборе capabilities (PRD §50)

## Out of scope M3

- YAxUnit / Vanessa / docs index (→ M4)
- DAP, semantic diff, verify против `.cf` как baseline (→ M5; там же углубление `runtime.load` для CI)
- Remote runtime / Docker / lockfile (→ M6)
- `.cf` как постоянный source format в манифесте (`source.format: cf`)
- Публичный `source.write` как замена `metadata.create`

## Manual verification

```bash
# 1. Import from CF
1c-dev project import --from /path/to/configuration.cf --output json

# 2. Read metadata (M2)
1c-dev metadata list --output json

# 3. Build / check
1c-dev build --output json
1c-dev check --output json

# 4. Convert to EDT (если EDT CLI доступен)
1c-dev source convert --to=edt --output json
1c-dev build --output json
1c-dev check --output json
```

## Links

- [Roadmap](../roadmap.md)
- [M1](m1-catalog-via-agent.md)
- [M2](m2-metadata-api.md)
- [PRD §12 Source API](../../1c-dev-runtime-PRD-v0.1.md), [§13 Sync](../../1c-dev-runtime-PRD-v0.1.md), [§49 Format switching](../../1c-dev-runtime-PRD-v0.1.md)
- ADR: XML/EDT adapters, source sync — завести при старте реализации M3

## Suggested work packages

| Тема | Зависит от |
|------|------------|
| Platform: `config load` + `config export` (ibcmd) | M1 build/check |
| CLI/MCP `project.import` / `runtime.load` | platform load/export |
| EDT Source Adapter + doctor capability | M2 metadata read |
| `source.convert` XML ↔ EDT | оба adapters |
| Contract tests + acceptance M3 | import + convert |
