# M1: catalog via agent

## Goal

AI-агент через MCP создаёт конфигурацию 1С с одним справочником без ручного Конфигуратора.

## Prerequisites

- Платформа 1С 8.3.x (локально)
- `ibcmd` в PATH
- Linux или Windows
- Runtime-зависимости — по [ADR-001](../adr/001-language-core-cli.md) (Python 3.11+ / Go / Rust — что будет выбрано)

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

- EDT adapter
- `metadata.list` / `metadata.get` / `metadata.find` (→ M2)
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
- [PRD §47](../../1c-dev-runtime-PRD-v0.1.md)
