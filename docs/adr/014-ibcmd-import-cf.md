# ADR-014: Platform adapter ibcmd import from `.cf`

**Статус:** Accepted  
**Дата:** 2026-09-26

## Контекст

Issue #46 и [M3](../milestones/m3-product-adopt.md) требуют обратный к build путь: загрузить `.cf` в file IB и выгрузить XML source. Build (ADR-008) уже умеет XML → IB (`import`/`apply`) и IB → `.cf` (`config save`); check — ADR-009. Нужен контракт adapter-слоя `config load` / `config export` без CLI/MCP (это #47).

## Решение

### Пакет

`adapters/platform_ibcmd/` — subprocess wrappers `load_cf` / `export_xml` и оркестратор `import_cf_with_ibcmd`.  
Публичный CLI/MCP `project.import` / dirty-source / `--force` — #47.

### Pipeline

```text
ibcmd infobase create --db-path=<runtime.path> --data=<root>/.runtime/ibcmd-data   # если нет 1Cv8.1CD
ibcmd infobase config load  --db-path=… --data=… <file.cf>
ibcmd infobase config apply --db-path=… --data=… --force
ibcmd infobase config export --db-path=… --data=… <source.path>
```

Те же `--db-path` / `--data`, что в build. Путь к `.cf` и каталог XML — positional (как у `import`), не флаг `--db` (он у `config save`).

`create` выполняется только если в `runtime.path` нет маркера `1Cv8.1CD`.

### Критерий успеха

Успех = create (при необходимости) + load + apply + export.  
Минимальная проверка результата export — наличие `Configuration.xml` в целевом каталоге (на уровне #47 / integration).

### Diagnostics

Ошибки шагов ibcmd → structured diagnostics через `_require_ok` / `diagnostics_from_output`, код `1CB005` (`CODE_IBCMD_FAILED`), `source: "platform"`. Отдельные exit codes и project-level коды — в оркестрации #47.

### Граница с #47

- Adapter only: нет CLI, MCP, манифеста, политики dirty source.
- `runtime.load` (только CF → IB без export) — should CLI в #47; reuse `load_cf` + `apply_config`.

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| `infobase config load` / `export` | Совпадает с докой платформы и `import`/`apply` | — | **Принято** |
| Top-level `config load` (как `config save`) | Единообразие с `save_cf` | Нет в примерах load/export; ломает симметрию с import | Отвергнуто |
| `infobase create --load=… --apply` одним шагом | Короче | Сложнее reuse; нет отдельного export | Отвергнуто |
| CLI в этом же issue | Быстрее end-to-end | Смешивает adapter и product API | Отложено (#47) |

## Последствия

- #47 (`project.import`) переиспользует `import_cf_with_ibcmd`.
- Integration round-trip: `build --artifact cf` → `import_cf_with_ibcmd`; skip без platform.
- Бинарный `.cf` в git не коммитим.

## Связанные решения

- ADR-003, ADR-005, ADR-008, ADR-009
- Issue #46
- [M3 Product adopt](../milestones/m3-product-adopt.md)
