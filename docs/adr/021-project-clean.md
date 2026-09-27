# ADR-021: Product API `project.clean` (source + runtime)

**Статус:** Accepted  
**Дата:** 2026-09-27

## Контекст

После `project.import`, экспериментов с metadata или неудачного `build` в каталоге проекта остаются XML source (`source.path`) и file IB (`.runtime/`). Dirty source блокирует повторный import без `--force` (ADR-015); отдельной команды «обнулить проект» нет — `tools clean` чистит только user cache toolchain (ADR-013), а PRD `runtime.reset` (§27) описывает лишь сброс IB.

Для adopt-сценариев M3 (повторный import другой `.cf`, откат к пустому source перед `init`/`import`) нужен явный destructive reset **source + runtime**, с сохранением манифеста и IDE-артефактов.

## Решение

### Контракт

```bash
1c-dev project clean --yes
# MCP: project.clean (confirm / yes обязателен)
```

Pipeline:

```text
require --yes (иначе отказ + diagnostic)
  → stop runtime-клиента при живом процессе (или отказ + suggestion runtime stop)
  → удалить содержимое source.path
  → удалить .runtime/ целиком (IB, ibcmd-data, client.pid / meta)
  → идемпотентно: уже пусто → ok
```

**Удаляет:**

- всё содержимое `source.path` из `1c.project.yaml` (каталог можно оставить пустым или пересоздать);
- весь `.runtime/` (включая `runtime.path`, даже если он указывает внутрь `.runtime/ib`).

**Не трогает:** `1c.project.yaml`, `AGENTS.md`, IDE MCP-конфиги, `.gitignore`, историю git, user cache toolchain.

Без `--yes` — отказ (как `tools clean --yes`, ADR-013). MCP требует тот же явный confirm.

Отличие от `project import --force`: force перезаписывает source через pipeline ibcmd; `clean` — явный wipe перед повторным import/init.

### Пакет

- `core/project/` (или узкий `core/project/clean.py`) — оркестрация `run_clean` + `CleanResult`.
- CLI: `1c-dev project clean`.
- MCP: `project.clean`.
- Diagnostics: серия product-кодов (конкретные `1CP*` / новые — в реализации #76); `source`: `"runtime"` / `"project"`.

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| Всегда source + runtime | Простой контракт; полный reset для adopt | Опаснее для агента (source в git) | **Принято** (MVP) |
| Default только runtime; `--source` опционально | Безопаснее | Два режима; путаница с `runtime.reset` | Отложено |
| Только `runtime.reset` (PRD) | Уже в PRD | Не решает dirty source / повторный import | Недостаточно |
| Reuse `tools clean` | Меньше команд | Другое пространство (user cache ≠ project) | Отвергнуто |
| Без `--yes` | Короче CLI | Слишком легко стереть source из MCP | Отвергнуто |

## Последствия

- Типовой цикл: `project clean --yes` → `project import --from …` (или `init`).
- Агент обязан передавать confirm; в AGENTS.md — предупреждение о destructive.
- Unit-тесты на tmp fixture (файлы в `source.path` + `.runtime/ib`) без platform.
- `runtime.reset` (только IB) и режим «только runtime» — later, не M3 must.

## Связанные решения

- [ADR-004](004-project-manifest.md), [ADR-013](013-packaging-toolchain-cache.md), [ADR-015](015-project-import-cf.md), [ADR-019](019-runtime-client-lifecycle.md)
- Issue [#76](https://github.com/pila86/1c-dev/issues/76)
- [M3 Product adopt](../milestones/m3-product-adopt.md)
