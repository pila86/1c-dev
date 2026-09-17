# Architecture Decision Records (ADR)

Значимые архитектурные решения фиксируются здесь.

## Формат

Используй [000-template.md](000-template.md).

Именование: `NNN-short-title.md` (например, `001-language-core-cli.md`).

## Индекс

| ADR | Статус | Тема |
|-----|--------|------|
| [001](001-language-core-cli.md) | Accepted | Язык core/CLI: Python 3.11+ + Poetry |
| [002](002-monorepo-layout.md) | Accepted | Layout monorepo |
| [003](003-diagnostics-exit-codes.md) | Accepted | Diagnostics model + exit codes |
| [004](004-project-manifest.md) | Accepted | Project manifest `1c.project.yaml` |
| [005](005-environment-discovery.md) | Accepted | Environment discovery (`doctor`) |

## Когда писать ADR

- Выбор языка, фреймворка, протокола
- Структура monorepo
- Модель данных (metadata IR)
- Границы между API (source vs metadata vs build)
- Отвергнутые альтернативы с обоснованием
