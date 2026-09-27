# ADR-019: Runtime client lifecycle (start / stop / status)

**Статус:** Accepted  
**Дата:** 2026-09-27

## Контекст

PRD §27 задаёт Runtime API (`runtime.start` / `stop` / `status`). Сейчас CLI умеет
только `runtime load` (ADR-015); MCP runtime-tools нет. Агенту нужен способ поднять
толстый клиент к file IB без shell/`1cv8` вручную, с заделом под отладку (PRD §28 / M6 DAP).

## Решение

### Пакет

- `adapters/platform_1cv8/` — argv + detach-`Popen` + process helpers (Linux/Windows).
- `core/runtime/` — оркестрация `run_start` / `run_stop` / `run_status`, `RuntimeResult`.
- CLI: `1c-dev runtime start|stop|status` (рядом с существующим `runtime load`).
- MCP: `runtime.start` / `runtime.stop` / `runtime.status` (thin wrappers, ADR-010).

Discovery `1cv8` / `1cv8.exe` — reuse ADR-005.

### Контракт MVP

- Только **file IB** (`runtime.path`, маркер `1Cv8.1CD`) и режим **ENTERPRISE**.
- Только **detach** (быстрый JSON-ответ; foreground — later).
- Argv: `1cv8 ENTERPRISE /F<abs-ib> [/Debug]`.
- Состояние: `.runtime/client.pid` (текст pid) + `.runtime/client.meta.json`
  (`mode`, `debug.enabled`).
- Повторный `start` при живом процессе — idempotent (тот же pid).
- Stale pid → status `running=false`, файлы чистятся.

### Debug (закладка, не DAP)

Флаг CLI `--debug` / MCP `debug=true` добавляет `/Debug` в argv и пишет
`debug.enabled` в meta. Tools `debug.*`, `debuggerUrl`, attach через
bsl-debug-server / DAP — **M6**, не этот ADR.

### Кроссплатформенность

Must: **Linux + Windows** (паритет с ADR-005). Helpers `is_running` / `terminate` /
`spawn_detached` с веткой `sys.platform == "win32"`. Без `shell=True`.

Вне MVP: macOS; WSL использует Linux-гость и свой `1cv8` внутри WSL.

### Diagnostics и exit codes

| Ситуация | Code | Exit |
|----------|------|------|
| Нет `1cv8` | `1CR001` | `ENV_UNAVAILABLE` (3) |
| Нет/битый проект / манифест | `1CR002` | `PROJECT_ERROR` (2) |
| Нет file IB (`1Cv8.1CD`) | `1CR003` | `PROJECT_ERROR` (2) |
| Клиент сразу завершился / ошибка процесса | `1CR004` | `RUNTIME_FAILURE` (4) |

`source` в diagnostics: `"platform"` для discovery; `"runtime"` для product.

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| Detach + pid + `/Debug` flag | Готовый клиент; задел к M6 | GUI нужен на машине | **Принято** |
| Только reserved flag без `/Debug` | Меньше argv | Потом всё равно менять launch | Отвергнуто |
| Заглушки MCP `debug.*` сейчас | Видимость API | Шум для агента до DAP | Отвергнуто |
| Foreground start | Проще debug вручную | Блокирует CLI/MCP | Отложено |
| DESIGNER / thin client | Шире сценарии | Scope | Отложено |

## Последствия

- README / AGENTS.md / ADR-010: новые runtime tools.
- Doctor по-прежнему warning без `1cv8`; `runtime.start` — жёсткий `1CR001`.
- M6: `debug.start` attach к уже запущенному клиенту с `/Debug`.

## Связанные решения

- ADR-005, ADR-008, ADR-010, ADR-015
- PRD §27, §28
- Roadmap M6
