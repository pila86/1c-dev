# ADR-009: Platform adapter ibcmd check

**Статус:** Accepted  
**Дата:** 2026-09-19

## Контекст

Issue #9 и M1 требуют `1c-dev check`: платформенная проверка конфигурации на file-IB после успешного `build`, со structured diagnostics и exit code 1. Build уже загружает XML через ibcmd (ADR-008); discovery `ibcmd` есть (ADR-005). Нужен контракт check без смешивания с build и без `check.static` (BSL LS — позже).

## Решение

### Пакет

`adapters/platform_ibcmd/` — subprocess `ibcmd infobase config check`.  
Оркестрация — `core/check/`; CLI — `1c-dev check` (default = platform; флаг `--platform` явный).

### Pipeline (M1)

```text
ibcmd infobase config check --db-path=<runtime.path> --data=<root>/.runtime/ibcmd-data
```

Те же `--db-path` / `--data`, что в build. Check **не** создаёт IB и **не** импортирует XML: нужна уже существующая file IB (маркер `1Cv8.1CD`). Если IB нет — ошибка с suggestion выполнить `1c-dev build`.

### Критерий успеха

Успех = `ibcmd … config check` с returncode 0.

### Diagnostics и exit codes

| Ситуация | Code | Exit |
|----------|------|------|
| Нет `ibcmd` | `1CC001` | `ENV_UNAVAILABLE` (3) |
| Нет/битый проект | `1CC002` | `PROJECT_ERROR` (2) |
| Нет file IB | `1CC003` | `PROJECT_ERROR` (2) |
| Ошибка / замечания check | `1CC004` | `CHECK_FAILURE` (1) |

`source` в diagnostics для платформы: `"platform"`.

### Граница с build и static

- `config check` не входит в `1c-dev build` (ADR-008).
- `check.static` (BSL Language Server) — вне M1 / #9.

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| Check только на существующей IB | Чёткий M1 flow; проще | Нужен предварительный build | **Принято** |
| Auto-build перед check | Один шаг для агента | Скрывает сбои build; дублирует #7 | Отвергнуто |
| Включить check в build | Меньше команд | Ломает разделение API; exit 6 vs 1 | Отвергнуто |
| `check.static` в M1 | Раньше BSL diagnostics | Нужен BSL LS; scope #9 | Отложено |

## Последствия

- MCP `check` (#6) переиспользует `core.check.run_check`.
- Doctor capability `check` уже требует `ibcmd`.
- Integration-тесты skip без платформы.

## Связанные решения

- ADR-003, ADR-005, ADR-008
- Issue #9
- PRD §24, §35–§36, §52
