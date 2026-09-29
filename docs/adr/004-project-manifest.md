# ADR-004: Project manifest (`1c.project.yaml`)

**Статус:** Accepted  
**Дата:** 2026-09-10

## Контекст

Проект описывается манифестом `1c.project.yaml` (PRD §8). Точная schema была открытым вопросом (PRD §69). Issue #2 требует JSON Schema и API `project info|validate|detect` с machine-readable ошибками и exit code 2.

## Решение

### Контракт

Источник истины (M1, исторический): schema `"1"` / корневой `1c.project.yaml`. **С M4** актуальный контракт — [`.1c-dev/project.yaml`](../../schemas/1c.project.schema.v2.json) schema `"2"` ([ADR-022](022-project-home.md)). Schema `"1"` и корневой манифест **не поддерживаются**.

Обязательные секции для M1 (архив):

| Секция | Поля | Заметки |
|--------|------|---------|
| `schema` | `"1"` | Версия формата манифеста |
| `project` | `name`, `type` | `type`: configuration \| extension \| external-data-processor \| external-report |
| `platform` | `version` | Строка версии платформы (например `8.3.27`) |
| `source` | `format`, `path` | `format`: xml \| edt |
| `runtime` | `type`, `path` | M1: только `type: file` |

Опциональные секции `artifacts`, `tests`, `tools` — допускаются как объекты без глубокой валидации (forward-compat). Неизвестные top-level ключи запрещены (`additionalProperties: false`).

### Реализация

- Парсинг YAML (`PyYAML`), валидация через `jsonschema` по файлу schema.
- Логика в `core/project/`; CLI — `1c-dev project …`.
- Ошибки → Diagnostics Model (ADR-003), exit code `PROJECT_ERROR` (2).

### Пример

```yaml
schema: "1"
project:
  name: shop
  type: configuration
platform:
  version: "8.3.27"
source:
  format: xml
  path: src/cf
runtime:
  type: file
  path: .runtime/ib
```

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| JSON Schema + jsonschema | Один контракт для CLI/MCP/агентов | Отдельная Python-модель | Принято |
| Только Pydantic | Удобный DX | Schema не отдельный артефакт | Отвергнуто для M1 |
| Полная schema PRD сразу (tests/tools/…) | «Готово на будущее» | Лишний scope M1 | Отложено (shallow optional) |

## Последствия

- `project init` (#4) должен генерировать манифест, валидный по этой schema.
- Расширение (`runtime.type: server`, lockfile) — через bump `schema` или additive optional fields + ADR.
- MCP `project.get` / `project.validate` (#6) переиспользуют `core/project`.
- **M4:** schema `"2"` (`configurations[]`, `runtimes[]`) — [ADR-022](022-project-home.md), [ADR-026](026-runtimes-array.md); [`schemas/1c.project.schema.v2.json`](../../schemas/1c.project.schema.v2.json). Layout только `.1c-dev/project.yaml` (#86). Dual-compat / `project migrate` (#93) — **сняты** (not planned).

## Связанные решения

- ADR-002, ADR-003
- ADR-022–026 (Accepted, M4)
- Issue #2
- PRD §8, §14, §69
- [M4](../milestones/m4-project-model.md)