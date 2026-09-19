# ADR-010: MCP architecture (M1)

**Статус:** Accepted  
**Дата:** 2026-09-19

## Контекст

Issue #6 и M1 требуют agent-facing MCP server: агент в Cursor проходит
`project.init → metadata.create → build → check` без shell и без Конфигуратора.
Core API уже готовы (ADR-004…009); нужен тонкий MCP-слой и CLI `1c-dev mcp`.

Локальный пакет из ADR-002 назван `mcp/`, что совпадает с именем официального
Python SDK на PyPI (`mcp`) и затеняет импорты SDK.

## Решение

### Пакет и CLI

- Локальный пакет: **`mcp_server/`** (не `mcp/`), чтобы не shadow’ить PyPI `mcp`.
- CLI: `1c-dev mcp` → `mcp_server.run()` поверх **stdio**.
- SDK: официальный `mcp>=1.9.0,<2`, API **FastMCP** (`mcp.server.fastmcp`),
  как в ADR-001. Upgrade на mcp 2.x / `MCPServer` — после M1.

### Граница с core

MCP — thin wrappers: tools вызывают `core.*` напрямую и возвращают
`result.to_payload()` (structured JSON). Не парсить stdout CLI.
Exit codes CLI на MCP не маппятся: статус и `diagnostics[]` внутри JSON.

### M1 tools

| Tool | Core |
|------|------|
| `project.get` | `validate_project` + `to_payload(include_manifest=True)` |
| `project.init` | `init_project` |
| `metadata.create` | IR builders + `create_metadata` |
| `build` | `run_build` |
| `check` | `run_check` |

Имена tools — с точками (как в PRD §32 / Issue #6).

Опциональный аргумент `path` (строка); если не передан — `Path.cwd()`.
Cursor обычно стартует MCP из workspace root.

В descriptions каждого tool — явный запрет shell / Designer для этой операции.

### Вне M1 / #6

- `shell.exec`, `doctor`, `project.validate` как MCP tools
- Streamable HTTP transport
- mcp SDK 2.x / `MCPServer`
- resources / prompts MCP

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| Пакет `mcp_server/` + pin `mcp<2` + FastMCP | Нет shadowing; стабильный API ADR-001 | Rename vs ADR-002 stub | **Принято** |
| Оставить локальный `mcp/` | Совпадает с деревом ADR-002 | Ломает импорт SDK | Отвергнуто |
| mcp 2.x / MCPServer сразу | Актуальный API | Major migration mid-M1 | Отложено |
| Парсить CLI stdout | Меньше кода «дубля» | Хрупко; text/json; exit codes | Отвергнуто |
| HTTP transport в M1 | Удобнее remote | Scope #6 = stdio | Отложено |

## Последствия

- Poetry packages / mypy: `mcp_server` вместо `mcp`.
- Dependency: `mcp>=1.9.0,<2`.
- README: как подключить `1c-dev mcp` в Cursor.
- Acceptance «агент только через MCP» — Issue #8; полный onboarding — #10.

## Связанные решения

- ADR-001, ADR-002, ADR-003–009
- Issue #6
- PRD §32, §33, R7
