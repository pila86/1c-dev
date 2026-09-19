# M1: catalog via agent

## Goal

AI-агент через MCP создаёт конфигурацию 1С с одним справочником без ручного Конфигуратора.

## Prerequisites

- Платформа 1С 8.3.x (локально)
- `ibcmd` в PATH
- Linux или Windows
- Runtime-зависимости — Python 3.11+ и Poetry ([ADR-001](../adr/001-language-core-cli.md))

## Agent workflow

Пример prompt для агента:

> Создай новую конфигурацию с одним справочником «Товары» (Catalog.Products) с реквизитом «Артикул» (String, 50).

Ожидаемая последовательность MCP tools:

```
1. project.init(type=configuration)
2. metadata.create(Catalog.Products, synonym="Товары", attributes=[...])
3. build
4. check
```

## Acceptance criteria

- [ ] `1c-dev init --type configuration` создаёт валидный проект
- [ ] `1c-dev doctor` показывает платформу и ibcmd (✓ или понятные ✗)
- [ ] `metadata.create` создаёт справочник в `src/` (XML)
- [ ] `1c-dev build` успешно собирает конфигурацию
- [ ] `1c-dev check` проходит без ошибок
- [ ] MCP tools покрывают весь flow (без shell.exec)
- [ ] Integration test M1 зелёный (или skip с сообщением, если нет platform)
- [ ] Результат — одна конфигурация с одним справочником

## Out of scope M1

- EDT adapter, `source.convert`, import из `.cf` (→ [M3](m3-source-formats.md))
- `metadata.list` / `get` / `find`, `metadata.update`, create кроме `Catalog` (→ [M2](m2-metadata-api.md))
- YAxUnit / Vanessa
- Documentation index / docs.search
- Semantic diff / verify
- DAP debug
- `source.write` как отдельный API (write только через `metadata.create`)

## Manual verification

```bash
# 1. Init
1c-dev init --type configuration --output json

# 2. Doctor
1c-dev doctor --output json

# 3. Create catalog (CLI или MCP)
1c-dev metadata create Catalog.Products \
  --synonym "Товары" \
  --output json

# 4. Build
1c-dev build --output json

# 5. Check
1c-dev check --output json
```

## Agent test (Cursor)

1. Подключить MCP: `1c-dev mcp`
2. Попросить агента: «Создай конфигурацию с справочником Товары и реквизитом Артикул»
3. Убедиться, что агент использует только MCP tools (не shell)
4. Проверить `build` и `check` — success

## Links

- [GitHub milestone M1](https://github.com/pila86/1c-dev/milestone/1)
- [Roadmap](../roadmap.md)
- [M2](m2-metadata-api.md) · [M3](m3-source-formats.md)
- [PRD §47](../../1c-dev-runtime-PRD-v0.1.md)

## Issues

| # | Задача | Depends on |
|---|--------|------------|
| [#1](https://github.com/pila86/1c-dev/issues/1) | ADR и каркас monorepo | — |
| [#2](https://github.com/pila86/1c-dev/issues/2) | Project manifest и project API | #1 |
| [#3](https://github.com/pila86/1c-dev/issues/3) | Doctor: discovery окружения | #2 |
| [#4](https://github.com/pila86/1c-dev/issues/4) | Project init: пустая configuration | #2, #3 |
| [#5](https://github.com/pila86/1c-dev/issues/5) | Metadata IR v0 + metadata.create | #4 |
| [#7](https://github.com/pila86/1c-dev/issues/7) | Platform adapter: ibcmd build | #3, #4 |
| [#9](https://github.com/pila86/1c-dev/issues/9) | Check: platform check | #7 |
| [#6](https://github.com/pila86/1c-dev/issues/6) | MCP server: agent-facing tools | #4, #5, #7, #9 |
| [#8](https://github.com/pila86/1c-dev/issues/8) | Acceptance test M1 | #6 |
| [#10](https://github.com/pila86/1c-dev/issues/10) | README и developer onboarding | #3, #6 |
