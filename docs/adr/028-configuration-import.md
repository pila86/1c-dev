# ADR-028: Product API `configuration.import`

**Статус:** Accepted  
**Дата:** 2026-09-29

## Контекст

После ADR-027 `project.init` создаёт empty scope (`configurations: []`), а lifecycle conf — через `configuration.*`. Публичный API всё ещё назывался `project.import` (ADR-015) и при ensure писал **полный** манифест с `main`/`src/cf`, либо при empty init лил XML в fallback `src/cf` **без** записи в `configurations[]`/`runtimes[]`. Нужны: (1) имя API в `configuration.*`; (2) семантика register через тот же путь, что `configuration.add`.

## Решение

1. **Публичный API:** CLI `1c-dev configuration import`, MCP `configuration.import`.  
   `project import` / MCP `project.import` — **удалены** (без alias).
2. **Doctor:** capability `configuration.import` → `ibcmd`.
3. **Оркестрация** (`core/import_cf/run_import`):
   - нет манифеста → ensure **empty** scope (`1c.project.empty.yaml.tmpl` + `.1c-dev/runtime` + `build`; **без** AGENTS/IDE);
   - нет conf с `--id` (default `main` при создании) → **register** conf+runtime (как `configuration.add`: path `src/<id>`, runtime `.1c-dev/runtime/<id>`, default/publish) **без** scaffold пустого XML;
   - conf есть → import в выбранную/`default` conf;
   - dirty-check `Configuration.xml` + `--force` / `--break-support` (ADR-020) без изменений по смыслу.
4. Общий helper регистрации conf/runtime в манифесте: reuse из `configuration.add` (add = register + scaffold).
5. `runtime.load` остаётся CLI should; suggestion указывает на `configuration.import` где уместно.
6. Коды diagnostics `1CI*` сохраняются (ADR-015).

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| `configuration.import` + empty ensure + register | Согласовано с ADR-027 | Breaking rename | **Принято** |
| Alias `project.import` | Мягче миграция | Два имени, путаница агентов | Отвергнуто |
| Оставить `project.import` | Нет churn | Ломает модель lifecycle | Отвергнуто |

## Последствия

- ADR-015: публичное имя `project.import` superseded этим ADR; pipeline/коды остаются.
- ADR-024 / M4: `--from-template` вешается на `configuration.import` (реализация — отдельно).
- ADR-027: в `configuration.*` добавляется `import`.
- Тесты/AGENTS/README/doctor schema обновляются под новое имя.

## Связанные решения

- ADR-014, ADR-015 (superseded name), ADR-020, ADR-022, ADR-024, ADR-027
- [M4](../milestones/m4-project-model.md)
