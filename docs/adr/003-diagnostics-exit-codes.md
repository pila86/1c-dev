# ADR-003: Diagnostics model + exit codes

**Статус:** Accepted  
**Дата:** 2026-09-10

## Контекст

Все подсистемы runtime (project, build, check, MCP) должны возвращать machine-readable ошибки и согласованные exit codes (PRD §35–§36, §52). Нужна единая модель с первого scaffold’а.

## Решение

### Exit codes

| Code | Константа | Meaning |
|------|-----------|---------|
| 0 | `SUCCESS` | success |
| 1 | `CHECK_FAILURE` | validation/check failure |
| 2 | `PROJECT_ERROR` | project/configuration error |
| 3 | `ENV_UNAVAILABLE` | required tool/environment unavailable |
| 4 | `RUNTIME_FAILURE` | runtime failure |
| 5 | `TEST_FAILURE` | test failure |
| 6 | `BUILD_FAILURE` | build failure |
| 7 | `CANCELLED` | cancelled |

Константы — в `core/exit_codes.py`.

### Diagnostics

Единый объект диагностики (минимум по PRD §36):

```json
{
  "severity": "error",
  "code": "1CXXXX",
  "message": "...",
  "file": "src/...",
  "object": "CommonModule.SalesServer",
  "module": "Module",
  "line": 42,
  "column": 10,
  "source": "platform"
}
```

Опциональные поля: `documentationLink`, `relatedObject`, `suggestion`, `fix`.

Черновик JSON Schema: [`schemas/diagnostics.schema.json`](../../schemas/diagnostics.schema.json).

CLI и MCP при ошибках возвращают structured JSON (массив `diagnostics` + `status`) и соответствующий exit code; raw stdout внешних инструментов сохраняется отдельно для debugging (PRD §52).

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| Модель PRD §35–§36 | Согласована со спецификацией | — | Принято |
| Только текстовые ошибки + ненулевой exit | Проще | Непригодно для агентов | Отвергнуто |
| Сырой stdout ibcmd без нормализации | Меньше кода | Ломает machine-readable API | Отвергнуто |

## Последствия

- Issues #2, #7, #9 используют эти exit codes (2 / 6 / 1 соответственно).
- Типы diagnostics в Python появятся в `core/` по мере реализации API; schema — источник истины для контракта.

## Связанные решения

- ADR-001, ADR-002
- Issue #1
- PRD §35, §36, §52
