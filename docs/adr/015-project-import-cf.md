# ADR-015: Product API `project.import` / `runtime.load`

**Статус:** Accepted  
**Дата:** 2026-09-26

## Контекст

Issue #47 и [M3](../milestones/m3-product-adopt.md) требуют публичный CLI/MCP поверх adapter ibcmd import (ADR-014): загрузка `.cf` в XML source, политика dirty source, ensure манифеста, should-CLI `runtime load`. Adapter `import_cf_with_ibcmd` уже есть; product-коды и оркестрация — здесь.

## Решение

### Пакет

`core/import_cf/` — оркестрация `run_import` / `run_runtime_load` и `ImportResult`.  
CLI: `1c-dev project import`, `1c-dev runtime load`.  
MCP: `project.import` (без `runtime.load` в M3).

Adapter: reuse `import_cf_with_ibcmd`; для load-only — `load_cf_with_ibcmd` (create? → load → apply).

### `project.import`

```text
ensure 1c.project.yaml (если нет — только манифест + .runtime dirs)
  → dirty-check Configuration.xml в source.path (без --force → отказ)
  → discover ibcmd
  → import_cf_with_ibcmd
  → проверить наличие Configuration.xml
```

- `--from` / MCP `from_path` — путь к `.cf`.
- `--force` — перезаписать существующий XML source.
- `--break-support` / MCP `break_support` — после export удалить `ParentConfigurations*` из `source.path` ([ADR-020](020-break-support.md)).
- Не пишет `AGENTS.md` / IDE MCP (это `ide configure`, #50).
- Пустой / отсутствующий `source.path` — import ок.

### `runtime load` (should, CLI only)

Манифест обязателен (как у build). Pipeline: create? → load → apply (без export).

### Diagnostics и exit codes

| Ситуация | Code | Exit |
|----------|------|------|
| Нет / недоступен файл `.cf` | `1CI001` | `PROJECT_ERROR` (2) |
| Нет `ibcmd` | `1CI002` | `ENV_UNAVAILABLE` (3) |
| Нет/битый проект / манифест | `1CI003` | `PROJECT_ERROR` (2) |
| Dirty source без `--force` | `1CI004` | `PROJECT_ERROR` (2) |
| Ошибка шага ibcmd | `1CB005` | `BUILD_FAILURE` (6) |
| После export нет `Configuration.xml` | `1CI005` | `BUILD_FAILURE` (6) |
| Уже снята с поддержки (нет артефактов) | `1CI006` | success + warning |
| Удалён артефакт поддержки | `1CI007` | success + info |

`source` в diagnostics для платформы: `"platform"`; для product — `"runtime"`.

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| Коды `1CI*` | Отделяет import от build/init | Ещё одна серия | **Принято** |
| Reuse `1CP004` для dirty | Меньше кодов | Смешивает init и import | Отвергнуто |
| MCP `runtime.load` в M3 | Полнота | Out of scope M3 (should CLI only) | Отложено |
| Import вызывает `ide configure` | Удобнее агенту | Нарушает разделение import / ide configure | Отвергнуто |

## Последствия

- Doctor capability `project.import` → `ibcmd`.
- Integration: `build --artifact cf` → `run_import`; skip без platform.
- Бинарный `.cf` в git не коммитим.
- **M4 (Proposed):** import в layout `.1c-dev/` + `project.import --from-template` ([ADR-022](022-project-home.md), [ADR-024](024-platform-templates.md)).

## Связанные решения

- ADR-003, ADR-004, ADR-006, ADR-008, ADR-014
- [ADR-020](020-break-support.md) (`--break-support` после export)
- [ADR-021](021-project-clean.md) (`project.clean` — wipe source + runtime перед повторным import)
- ADR-022, ADR-024 (Proposed)
- Issue #47
- [M3 Product adopt](../milestones/m3-product-adopt.md)
- [M4](../milestones/m4-project-model.md)
