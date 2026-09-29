# ADR-016: IDE configure (MCP + AGENTS merge)

**Статус:** Accepted  
**Дата:** 2026-09-26
**Обновлено:** 2026-09-29 (#90)

## Контекст

Issue #50 и [M3](../milestones/m3-product-adopt.md) требуют идемпотентно подключить runtime к уже существующему source (после `import` или clone): манифест, `AGENTS.md`, `.gitignore`, MCP-конфиг IDE. `init` — bootstrap пустой конфигурации (включая IDE MCP через `_configure_ide_mcp`); `import` агентские артефакты не пишет (ADR-015).

M4 / [ADR-022](022-project-home.md): в multi-tool monorepo IDE MCP может жить в workspace root, а scope — nested; чужой корневой `AGENTS.md` оркестратора нельзя затирать без opt-in (#90).

## Решение

### CLI / MCP

- CLI: `1c-dev ide configure [--project PATH] [--ide-root PATH] [--agents auto|scope|none] [--target all|cursor|kilocode|none] [--force]`; алиас `1c-dev project ide configure`.
- MCP: `ide.configure` (path, ide_root, agents, target, force) без shell.exec.
- Default `--target all` — прописать MCP для обеих IDE; `none` — только манифест / AGENTS / `.gitignore` (по `--agents`).
- **`--project`** = scope root (манифест, `.gitignore`, AGENTS). Default: CWD.
- **`--ide-root`** = куда писать `.cursor` / `.kilo`. Default: = project.
- **`--agents`:** `auto` (default) — писать AGENTS в project только если `ide-root == project`; `scope` — всегда в project; `none` — не трогать AGENTS. При `ide-root ≠ project` корневой AGENTS под ide-root **не пишется** (даже с `--force`).

### IDE MCP paths

Оба файла — схема `mcpServers` (Cursor и Kilocode VS Code), относительно **ide-root**:

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
| `.gitignore` | дописать только недостающие строки (в project) |
| IDE MCP | добавить servers `1c-dev` / `bsl-language-server`, если ключей нет; чужие и уже заданные — не трогать (в ide-root) |
| `AGENTS.md` | managed-блок `<!-- BEGIN 1c-dev -->` … `<!-- END 1c-dev -->`: create / upsert блока / skip если без изменений; текст вне блока сохранить |
| `.1c-dev/project.yaml` | если нет — создать из tmpl; если есть — только validate, поля не перезаписывать |

С `--force`: перезаписать AGENTS (целиком шаблоном, если `--agents` разрешает запись), `.gitignore`, MCP целиком из шаблона; манифест — create-if-missing / validate (не клоббировать `source`/`runtime`).

### Diagnostics

| Ситуация | Code | Severity |
|----------|------|----------|
| Неизвестный `--target` | `1CP007` | error |
| Неизвестный `--agents` | `1CP010` | error |
| jar BSL LS не найден | `1CP009` | warning |

`1CP008` (skip AGENTS без force) снят — заменён merge по маркерам.

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| Default `--target all` | Один вызов покрывает Cursor и Kilocode | Лишний файл, если нужна одна IDE | **Принято** |
| `--target` optional / omit = none | Меньше файлов по умолчанию | Хуже DX для M3 onboarding | Отвергнуто |
| Писать `cwd` в mcp.json | Явный корень | Лишнее; IDE даёт workspace cwd | Отвергнуто |
| Kilo CLI `kilo.jsonc` | Новый формат | Другой продукт; M3 — VS Code plugin | Отложено |
| CLI `setup` / MCP `project.setup` | Короче | Неясно, что настраивается IDE | Отвергнуто → `ide configure` |
| AGENTS skip без force | Не затирает правки | Не обновляет шаблон; плохо для monorepo merge | Superseded → managed-блок |

## Последствия

- `init` и `ide configure` делят шаблон `AGENTS.md` и запись IDE MCP через `_configure_ide_mcp`.
- `init --ide-target all` (default) сразу создаёт `.cursor/mcp.json` и `.kilo/mcp.json` в scope; `ide configure` — adopt (после import/clone), split roots и повторный merge.
- Doctor / `tools sync` обеспечивают jar для рабочего BSL LS MCP.
- Monorepo: `ide configure --project products/shop --ide-root . [--agents scope]`.

## Связанные решения

- ADR-006, ADR-010, ADR-013, ADR-015, ADR-022
- Issue #50, #90
- [M3 Product adopt](../milestones/m3-product-adopt.md)
- [M4](../milestones/m4-project-model.md)
