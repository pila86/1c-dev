# ADR-027: Configuration lifecycle (init vs configuration.*)

**Статус:** Accepted  
**Дата:** 2026-09-29

## Контекст

M4 допускает несколько `configurations[]` в одном scope (ADR-023), но `project.init` сразу scaffold’ил одну conf + XML + runtime. Повторный init падал с `1CP004` и suggestion на `extension add` — ложный путь для «ещё одной конфигурации». Нужен dedicated lifecycle API ([#100](https://github.com/pila86/1c-dev/issues/100)).

## Решение

1. **`project.init` (`--type configuration`)** создаёт только empty scope:
   - `.1c-dev/project.yaml` schema `"2"` с `configurations: []`, `runtimes: []`;
   - AGENTS / `.gitignore` / `build/` / `.1c-dev/runtime/` (каталог);
   - **без** XML configuration.
2. **`configuration.add|list|get|remove|set-default|import`** (CLI + MCP) — lifecycle conf:
   - `add`: scaffold XML (`src/<id>/` или `--path`), append `configurations[]`, связанный runtime `.1c-dev/runtime/<id>` (`--with-runtime`, default on), `default: true` если первая; при первом runtime — default publish-профиль `local-webinst` (Apache);
   - `import`: `.cf` → XML source ([ADR-028](028-configuration-import.md)); register conf/runtime без empty scaffold, если conf ещё нет;
   - `list` / `get` / `remove --yes` / `set-default`.
3. **Сахар:** `project.init --config <name>` ≡ empty init + `configuration.add`.
4. **`project.get` / `project.info`:** payload включает `summary` (configurations, runtimes, defaults).
5. Schema/validate: empty arrays OK; «≥1 runtime на conf» и «ровно один default runtime» — только когда массивы непусты.
6. `--type extension` (standalone) без изменений (ADR-023).
7. Suggestion при повторном init / пустом resolve / extension без conf → `configuration.add`, не `extension add` для второй conf.

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| Init = empty + `configuration.*` | Явный agent workflow; multi-config | Два шага greenfield | **Принято** |
| Init сразу с conf (как ADR-006) | Один шаг | Нет API для второй conf | Superseded |
| Только `init --config` без `configuration.add` | Короче CLI | Нет add в существующий scope | Отвергнуто |

## Последствия

- ADR-006 superseded этим ADR (фрагмент «init = bootstrap conf + XML»).
- ADR-023 / ADR-026 дополнены: init ≠ conf+runtime; empty arrays допустимы.
- Happy-path агента: `init` → `configuration.add` → `project.get` → metadata/build.
- Онбординг из `.cf`: `configuration.import` (ADR-028), не `project.import`.

## Связанные решения

- ADR-006 (superseded), ADR-022, ADR-023, ADR-026, ADR-028
- Issue #100
- [M4](../milestones/m4-project-model.md)
