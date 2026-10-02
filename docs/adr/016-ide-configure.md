# ADR-016: IDE configure (MCP + rules + AGENTS merge)

**Статус:** Accepted  
**Дата:** 2026-09-26
**Обновлено:** 2026-10-02 (IDE rules pack)

## Контекст

Issue #50 и [M3](../milestones/m3-product-adopt.md) требуют идемпотентно подключить runtime к уже существующему source (после `import` или clone): манифест, `AGENTS.md`, `.gitignore`, MCP-конфиг IDE. `init` — bootstrap пустой конфигурации (включая IDE MCP через `_configure_ide_mcp`); `import` агентские артефакты не пишет (ADR-015).

M4 / [ADR-022](022-project-home.md): в multi-tool monorepo IDE MCP может жить в workspace root, а scope — nested; чужой корневой `AGENTS.md` оркестратора нельзя затирать без opt-in (#90).

Помимо MCP и AGENTS нужны **IDE rules** (coding conventions BSL / URL сервисов): Cursor `.cursor/rules/*.mdc`, Kilocode `.kilo/rules/*.md`. `AGENTS.md` остаётся про lifecycle/MCP tools; rules — про стиль кода.

## Решение

### CLI / MCP

- CLI: `1c-dev ide configure [--project PATH] [--ide-root PATH] [--agents auto|scope|none] [--target all|cursor|kilocode|none] [--force]`; алиас `1c-dev project ide configure`.
- MCP: `ide.configure` (path, ide_root, agents, target, force) без shell.exec.
- Default `--target all` — прописать MCP **и** IDE rules от `1c-dev` для обеих IDE; `none` — только манифест / AGENTS / `.gitignore` (по `--agents`); MCP и rules не пишутся.
- **`--project`** = scope root (манифест, `.gitignore`, AGENTS). Default: CWD.
- **`--ide-root`** = куда писать `.cursor` / `.kilo`. Default: = project.
- **`--agents`:** `auto` (default) — писать AGENTS в project только если `ide-root == project`; `scope` — всегда в project; `none` — не трогать AGENTS. При `ide-root ≠ project` корневой AGENTS под ide-root **не пишется** (даже с `--force`).
- Отдельный флаг `--rules` **не** вводим: rules следуют `--target` как MCP.

### IDE MCP paths

Оба файла — схема `mcpServers` (Cursor и Kilocode VS Code), относительно **ide-root**:

| IDE | Путь |
|-----|------|
| `cursor` | `.cursor/mcp.json` |
| `kilocode` | `.kilo/mcp.json` |

Серверы в шаблоне:

- `1c-dev`: `command: 1c-dev`, `args: ["mcp"]` (без `cwd` — IDE стартует из workspace root).
- `bsl-language-server`: `java -jar <abs jar> mcp` (jar из toolchain resolve / ожидаемый cache path).

### IDE rules paths

Канонические тела: `templates/configuration/rules/*.md` + `rules.manifest.yaml`. При записи рендер под IDE (относительно **ide-root**):

| IDE | Каталог | Расширение | Managed-маркер |
|-----|---------|------------|----------------|
| `cursor` | `.cursor/rules/` | `.mdc` | frontmatter `managedBy: 1c-dev` |
| `kilocode` | `.kilo/rules/` | `.md` | первая substantive-строка `<!-- managed-by: 1c-dev -->` |

Набор rules от `1c-dev` (MVP):

- `bsl-string-literals`
- `bsl-module-structure`
- `1c-service-addresses`
- `bsl-transactions`

Cursor: все правила с `alwaysApply: true` и `description` из manifest `title`.

### Merge без `--force`

| Артефакт | Поведение |
|----------|-----------|
| файл отсутствует | создать из шаблона |
| `.gitignore` | дописать только недостающие строки (в project) |
| IDE MCP | добавить servers `1c-dev` / `bsl-language-server`, если ключей нет; чужие и уже заданные — не трогать (в ide-root) |
| IDE rules | create-if-missing; managed — обновить тело при отличии; чужой файл с тем же именем — skip + `1CP011` |
| `AGENTS.md` | managed-блок `<!-- BEGIN 1c-dev -->` … `<!-- END 1c-dev -->`: create / upsert блока / skip если без изменений; текст вне блока сохранить |
| `.1c-dev/project.yaml` | если нет — создать из tmpl; если есть — только validate, поля не перезаписывать |

С `--force`: перезаписать AGENTS (целиком шаблоном, если `--agents` разрешает запись), `.gitignore`, MCP целиком из шаблона; managed rules — перезаписать при отличии; чужие rules не удалять и не перезаписывать; манифест — create-if-missing / validate (не клоббировать `source`/`runtime`).

### Diagnostics

| Ситуация | Code | Severity |
|----------|------|----------|
| Неизвестный `--target` | `1CP007` | error |
| Неизвестный `--agents` | `1CP010` | error |
| jar BSL LS не найден | `1CP009` | warning |
| Чужой IDE rule (нет managed-маркера) | `1CP011` | warning |

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
| Отдельный `--rules` / `ide rules` | Гибкость | Лишняя поверхность; rules = часть IDE target | Отвергнуто (MVP) |
| Дублировать BSL-конвенции в AGENTS | Один файл | Раздувает AGENTS; хуже file-scoped rules | Отвергнуто → IDE rules pack |

## Последствия

- `init` и `ide configure` делят шаблон `AGENTS.md`, запись IDE MCP через `_configure_ide_mcp` и rules агента через `_configure_ide_rules`.
- `init --ide-target all` (default) сразу создаёт `.cursor/mcp.json`, `.kilo/mcp.json` и IDE rules от `1c-dev` в scope; `ide configure` — adopt (после import/clone), split roots и повторный merge.
- Doctor / `tools sync` обеспечивают jar для рабочего BSL LS MCP.
- Monorepo: `ide configure --project products/shop --ide-root . [--agents scope]`.

## Связанные решения

- ADR-006, ADR-010, ADR-013, ADR-015, ADR-022
- Issue #50, #90
- [M3 Product adopt](../milestones/m3-product-adopt.md)
- [M4](../milestones/m4-project-model.md)
