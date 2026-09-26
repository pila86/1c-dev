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
| [006](006-project-init.md) | Accepted | Project init (bootstrap configuration) |
| [007](007-metadata-ir.md) | Accepted | Metadata IR v0 + write-backend xml-gen |
| [008](008-ibcmd-build.md) | Accepted | Platform adapter: ibcmd build |
| [009](009-ibcmd-check.md) | Accepted | Platform adapter: ibcmd check |
| [010](010-mcp-architecture.md) | Accepted | MCP architecture (M1 stdio + tools) |
| [011](011-metadata-ir-v1.md) | Accepted | Metadata IR v1 (M2 contract) |
| [012](012-metadata-read-mdclasses.md) | Accepted | Metadata read-backend MDClasses |
| [013](013-packaging-toolchain-cache.md) | Accepted | Packaging (`uv tool`) / user cache / pin toolchain |
| [014](014-ibcmd-import-cf.md) | Accepted | Platform adapter: ibcmd import from `.cf` |
| [015](015-project-import-cf.md) | Accepted | Product API: `project.import` / `runtime.load` |

## Когда писать ADR

- Выбор языка, фреймворка, протокола
- Структура monorepo
- Модель данных (metadata IR)
- Границы между API (source vs metadata vs build)
- Отвергнутые альтернативы с обоснованием
