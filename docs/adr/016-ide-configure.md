# ADR-016: IDE configure (MCP + AGENTS merge)

**Статус:** Accepted  
**Дата:** 2026-09-26

## Контекст

Issue #50 и [M3](../milestones/m3-product-adopt.md) требуют идемпотентно подключить runtime к уже существующему source (после `import` или clone): манифест, `AGENTS.md`, `.gitignore`, MCP-конфиг IDE. `init` — bootstrap пустой конфигурации; `import` агентские артефакты не пишет (ADR-015).

## Решение

### CLI / MCP

- CLI: `1c-dev ide configure [--target all|cursor|kilocode|none] [--force]`; алиас `1c-dev project ide configure`.
- MCP: `ide.configure` (path, target, force) без shell.exec.
- Default `--target all` — прописать MCP для обеих IDE; `none` — только манифест / AGENTS / `.gitignore`.

### IDE MCP paths

Оба файла — схема `mcpServers` (Cursor и Kilocode VS Code):

| IDE | Путь |
|-----|------|
| `cursor` | `.cursor/mcp.json` |
| `kilocode` | `.kilo/mcp.json` |

Серверы в шаблоне:

- `1c-dev`: `command: 1c-dev`, `args: ["mcp"]` (без `cwd` — IDE стартует из workspace root).
- `bsl-language-server`: `java -jar <abs jar> mcp` (jar из toolchain resolve / ожидаемый cache path).

### Merge без `--force`

| Артефакт | Поведение |
|----------|-----------|
| файл отсутствует | создать из шаблона |
| `.gitignore` | дописать только недостающие строки |
| IDE MCP | добавить servers `1c-dev` / `bsl-language-server`, если ключей нет; чужие и уже заданные — не трогать |
| `AGENTS.md` | skip + warning `1CP008` |
| `1c.project.yaml` | если нет — создать из tmpl; если есть — только validate, поля не перезаписывать |

С `--force`: перезаписать AGENTS, `.gitignore`, MCP целиком из шаблона; манифест — create-if-missing / validate (не клоббировать `source`/`runtime`).

### Diagnostics

| Ситуация | Code | Severity |
|----------|------|----------|
| Неизвестный `--target` | `1CP007` | error |
| `AGENTS.md` уже есть (без force) | `1CP008` | warning |
| jar BSL LS не найден | `1CP009` | warning |

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| Default `--target all` | Один вызов покрывает Cursor и Kilocode | Лишний файл, если нужна одна IDE | **Принято** |
| `--target` optional / omit = none | Меньше файлов по умолчанию | Хуже DX для M3 onboarding | Отвергнуто |
| Писать `cwd` в mcp.json | Явный корень | Лишнее; IDE даёт workspace cwd | Отвергнуто |
| Kilo CLI `kilo.jsonc` | Новый формат | Другой продукт; M3 — VS Code plugin | Отложено |
| CLI `setup` / MCP `project.setup` | Короче | Неясно, что настраивается IDE | Отвергнуто → `ide configure` |

## Последствия

- `init` и `ide configure` делят шаблон `AGENTS.md` (разделение 1c-dev / bsl-ls / docs).
- Doctor / `tools sync` обеспечивают jar для рабочего BSL LS MCP.

## Связанные решения

- ADR-006, ADR-010, ADR-013, ADR-015
- Issue #50
- [M3 Product adopt](../milestones/m3-product-adopt.md)
