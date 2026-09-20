# M4: source formats (EDT)

## Goal

Единый agent/CLI API для работы с конфигурацией независимо от source format (XML и EDT): Source Adapter для EDT и `source.convert` без смены agent-level API.

## Prerequisites

- M2: Metadata API по XML source
- M3: `project.import` из `.cf` в XML (онбординг артефакта уже есть)
- Для EDT-ветки: `1cedtcli` (или согласованный EDT CLI) в окружении

## Scope

### 1. EDT adapter

- Source Adapter для EDT рядом с XML
- `source.convert` XML ↔ EDT без смены agent-level API
- `build` / `check` / `metadata.*` / `docs.*` работают одинаково при `source.format: edt`

### 2. Convert после import (опциональный flow)

```bash
1c-dev project import --from configuration.cf   # XML (M3)
1c-dev source convert --to=edt
```

## Agent workflows

### Переключение формата

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
- [ ] MCP: `source.convert` без shell.exec
- [ ] Integration-тесты: skip с сообщением, если нет EDT CLI
- [ ] Contract tests Source Adapter: XML и EDT на общем наборе capabilities (PRD §50)

## Out of scope M4

- Import из `.cf` (уже [M3](m3-product-adopt.md))
- YAxUnit / Vanessa (→ M5)
- DAP, semantic diff, verify (→ M6)
- Remote runtime / Docker / lockfile (→ M7)
- `.cf` как постоянный source format в манифесте (`source.format: cf`)
- Публичный `source.write` как замена `metadata.create`

## Manual verification

```bash
# После import (M3) или на существующем XML-проекте
1c-dev source convert --to=edt --output json
1c-dev metadata list --output json
1c-dev build --output json
1c-dev check --output json

1c-dev source convert --to=xml --output json
```

## Links

- [Roadmap](../roadmap.md)
- [M2](m2-metadata-api.md)
- [M3](m3-product-adopt.md)
- [PRD §12 Source API](../../1c-dev-runtime-PRD-v0.1.md), [§13 Sync](../../1c-dev-runtime-PRD-v0.1.md), [§49 Format switching](../../1c-dev-runtime-PRD-v0.1.md)
- ADR: XML/EDT adapters, source sync — завести при старте реализации M4

## Suggested work packages

| Тема | Зависит от |
|------|------------|
| EDT Source Adapter + doctor capability | M2 metadata read |
| `source.convert` XML ↔ EDT | оба adapters |
| Contract tests + acceptance M4 | convert |
