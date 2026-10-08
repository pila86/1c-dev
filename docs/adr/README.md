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
| [006](006-project-init.md) | Superseded by [027](027-configuration-lifecycle.md) | Project init (bootstrap; historical M1–M3) |
| [007](007-metadata-ir.md) | Accepted | Metadata IR v0 + write-backend xml-gen |
| [008](008-ibcmd-build.md) | Accepted | Platform adapter: ibcmd build |
| [009](009-ibcmd-check.md) | Accepted | Platform adapter: ibcmd check |
| [010](010-mcp-architecture.md) | Accepted | MCP architecture (M1 stdio + tools) |
| [011](011-metadata-ir-v1.md) | Accepted | Metadata IR v1 (M2 contract) |
| [012](012-metadata-read-mdclasses.md) | Accepted | Metadata read-backend MDClasses |
| [013](013-packaging-toolchain-cache.md) | Accepted | Packaging (`uv tool`) / user cache / pin toolchain |
| [014](014-ibcmd-import-cf.md) | Accepted | Platform adapter: ibcmd import from `.cf` |
| [015](015-project-import-cf.md) | Superseded by [028](028-configuration-import.md) | Product API: historical `project.import` / `runtime.load` |
| [016](016-ide-configure.md) | Accepted | IDE configure (MCP + rules + AGENTS merge) |
| [017](017-docs-bsl-context.md) | Accepted | Docs API via bsl-context (lazy index) |
| [018](018-metadata-types-coverage.md) | Accepted | Metadata types coverage (23 meta + Subsystem) |
| [019](019-runtime-client-lifecycle.md) | Accepted | Runtime client lifecycle (`start` / `stop` / `status`, `/Debug`) |
| [020](020-break-support.md) | Accepted | Снятие конфигурации с поддержки (XML / `--break-support`) |
| [021](021-project-clean.md) | Accepted | Product API: `project.clean` (source + runtime) |
| [022](022-project-home.md) | Accepted | Project home `.1c-dev/` (scope root; schema `"2"` only) |
| [023](023-multi-config-extensions.md) | Accepted | Multi-configuration + extensions |
| [024](024-platform-templates.md) | Accepted | Platform templates (tmplts / `*.mft`) |
| [025](025-publish-backends.md) | Accepted | Publish backends (ibsrv / webinst) |
| [026](026-runtimes-array.md) | Accepted | `runtimes[]`: ИБ ↔ configuration |
| [027](027-configuration-lifecycle.md) | Accepted | Init = empty scope; `configuration.*` lifecycle |
| [028](028-configuration-import.md) | Accepted | Product API: `configuration.import` (supersedes `project.import` name) |
| [029](029-test-api.md) | Accepted | Test API facade + граница с METR (CLI/MCP, exit 5, YaXUnit adapter) |
| [030](030-designer-check-modules.md) | Accepted | Designer `/CheckModules` в `1c-dev check` (синтаксис модулей) |

## Когда писать ADR

- Выбор языка, фреймворка, протокола
- Структура monorepo
- Модель данных (metadata IR)
- Границы между API (source vs metadata vs build)
- Отвергнутые альтернативы с обоснованием
