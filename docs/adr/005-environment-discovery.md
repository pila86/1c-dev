# ADR-005: Environment discovery (`doctor`)

**Статус:** Accepted  
**Дата:** 2026-09-17

## Контекст

Issue #3 и M1 требуют диагностики окружения: платформа 1С, `ibcmd`, `1cv8`, явные capability gaps. Полный PRD §37 шире (EDT, BSL LS, test runners, debugger) — для M1 нужен узкий, расширяемый контракт.

## Решение

### Scope M1

`1c-dev doctor` проверяет только:

- установленную платформу и версию;
- `ibcmd`;
- `1cv8`;
- capability gaps для `build` и `check` (оба требуют `ibcmd`).

Остальные tools из PRD §37 — в последующих issues.

### Размещение кода

| Слой | Пакет | Роль |
|------|-------|------|
| Discovery | `adapters/platform/` | Поиск установок и бинарников (PATH + known dirs) |
| Оркестрация | `core/doctor/` | Отчёт, capabilities, diagnostics |
| CLI | `cli/doctor.py` | Плоская команда `1c-dev doctor` |

Discovery вынесен в adapters, чтобы #7 (`ibcmd` build) переиспользовал те же пути без дублирования.

### Discovery rules

1. `shutil.which` для `ibcmd` / `1cv8`.
2. Probe known roots: Linux `/opt/1cv8/x86_64/*`, `/opt/1C/v8.3/x86_64`; Windows `Program Files\1cv8\*\bin`.
3. Версия — из имени каталога (`8.3.N.M`); без обязательного запуска процессов.
4. Несколько установок → новейшая по semver пути. Приоритет манифеста — позже (#4+).

### Exit code и статус

- `status: ok`, exit `0` — найдены `ibcmd` и платформа (версия или install path).
- `status: error`, exit `ENV_UNAVAILABLE` (3) — нет `ibcmd` и/или платформы.
- Отсутствие `1cv8` → warning (`1CD003`), не блокирует M1-зелёный отчёт.

Коды: `1CD001` platform, `1CD002` ibcmd, `1CD003` 1cv8.

JSON Schema: [`schemas/doctor.schema.json`](../../schemas/doctor.schema.json).

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| Узкий M1-doctor + adapters/platform | Совпадает с #3; готов к #7 | Неполный PRD §37 | Принято |
| Полный doctor сразу | «Готово на будущее» | Лишняя работа до adapters | Отложено |
| Discovery только в `core/` | Проще layout | Смешивает env probe с API | Отвергнуто |

## Последствия

- `adapters/platform_ibcmd/` (#7) опирается на `adapters.platform.discovery`.
- MCP/agent (#6) смогут вызывать тот же `run_doctor()`.
- Расширение doctor — новые probes + capabilities без смены exit-модели.

## Связанные решения

- ADR-002, ADR-003
- Issue #3
- PRD §37, §40
