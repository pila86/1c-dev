# ADR-022: Project home (`.1c-dev/`)

**Статус:** Accepted  
**Дата:** 2026-09-29

## Контекст

После M3 манифест `1c.project.yaml` лежит в «корне проекта», часто совпадающем с git root. В multi-tool monorepo (оркестратор, Inalytic, несколько продуктов) `1c-dev` не должен захватывать корень чужого workspace: IDE MCP, корневой `AGENTS.md` и чужие манифесты принадлежат другим инструментам. Нужен namespaced якорь и явный scope root.

## Решение

1. **Project home** = каталог `.1c-dev/` внутри scope.
2. **Манифест** = `.1c-dev/project.yaml` (schema `"2"`, см. ADR-023/026).
3. **Scope root** = родитель `.1c-dev/`. Все relative-пути в манифесте считаются от scope root.
4. Эфемерное по умолчанию под home: `.1c-dev/runtime/`, `.1c-dev/publish/`.
5. **Detect:** вверх от CWD/`path` искать только `.1c-dev/project.yaml`. Корневой `1c.project.yaml` (schema `"1"`) **не поддерживается** — ошибка `1CP016`, suggestion `project.init`. Init/import пишут только новый layout. Миграции (`project migrate`) нет.
6. **`project.list`:** от переданного корня сканировать вниз на ограниченную глубину в поисках `.1c-dev/project.yaml` (monorepo).
7. **`ide configure`:** флаги `--project` (scope) и `--ide-root` (куда писать `.cursor` / `.kilo`); по умолчанию ide-root = scope; в monorepo указывают git/workspace root. Не затирать чужой корневой `AGENTS.md` без явного opt-in.

Schema: [`schemas/1c.project.schema.v2.json`](../../schemas/1c.project.schema.v2.json). Milestone: [M4](../milestones/m4-project-model.md).

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| `.1c-dev/` + manifest внутри | Не мешает другим тулам; namespaced | Dot-dir менее заметен агентам | **Принято** |
| Манифест только в git root | Привычно | Конфликт monorepo | Отвергнуто |
| Произвольный `project.root` в env без home | Гибко | Нет единого якоря discovery | Отвергнуто как единственный механизм |

## Последствия

- Supersede path-assumptions в ADR-004/006/016/021 при реализации project home (#86); validate schema `"2"` (#85). Dual-compat schema `"1"` / корневой `1c.project.yaml` снят (closed #93 as not planned).
- MCP descriptions: `path` = scope root (родитель `.1c-dev`).
- Clean не трогает git root вне scope; wipe source — отдельный confirm.

## Связанные решения

- ADR-004, ADR-006, ADR-016, ADR-021
- ADR-023, ADR-026
- [M4](../milestones/m4-project-model.md)
