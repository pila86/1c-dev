# ADR-002: Layout monorepo

**Статус:** Accepted  
**Дата:** 2026-09-10

## Контекст

PRD §61 предлагает полный monorepo (`cli/`, `core/`, `adapters/`, `services/`, `mcp/`, `schemas/`, …). Для M1 нужен минимальный каркас, совместимый с будущим расширением и с ADR-001 (Python + Poetry).

## Решение

Корень репозитория — один Poetry-проект. Пакеты верхнего уровня соответствуют доменам runtime:

```text
1c-dev/
├── pyproject.toml
├── cli/                 # Typer entrypoint (`1c-dev`)
├── core/                # version, exit codes, diagnostics types
├── adapters/            # stubs; реализации — по мере issues (#3, #7, …)
├── mcp_server/          # MCP stdio server (Issue #6 / ADR-010; ранее stub `mcp/`)
├── schemas/             # JSON Schema (diagnostics, позже project)
├── tests/
├── .github/workflows/
└── docs/
    ├── adr/
    ├── milestones/
    └── roadmap.md
```

Poetry `packages` включают `cli`, `core`, `adapters`, `mcp_server`. Script entrypoint: `1c-dev = "cli.main:run"`.

Каталоги из PRD §61, не нужные в M1 scaffold (`services/`, `skills/`, `templates/`, `benchmarks/`), создаются по мере появления соответствующих issues.

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| Top-level domain packages (`cli/`, `core/`, …) | Совпадает с PRD; понятные границы | Несколько пакетов в одном Poetry | Принято |
| Единый `src/onec_dev/` | Классический Python layout | Расходится с PRD-деревом | Отвергнуто |
| Полное дерево PRD сразу | «Готово на будущее» | Пустой шум в M1 | Отложено |

## Последствия

- Новые adapters — подкаталоги в `adapters/` (например `adapters/platform_ibcmd/`).
- JSON Schema — в `schemas/`, не внутри Python-пакетов.
- CI и локальная разработка — из корня через Poetry.

## Связанные решения

- ADR-001
- Issue #1
