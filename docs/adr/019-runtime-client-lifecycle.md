# ADR-019: Runtime client lifecycle (start / stop / status)

**Статус:** Accepted  
**Дата:** 2026-09-27

## Контекст

PRD §27 задаёт Runtime API (`runtime.start` / `stop` / `status`). Сейчас CLI умеет
только `runtime load` (ADR-015); MCP runtime-tools нет. Агенту нужен способ поднять
клиент 1С (толстый или тонкий) к file IB без shell/`1cv8` вручную, с заделом под
отладку (PRD §28 / M6 DAP).

## Решение

### Пакет

- `adapters/platform_1cv8/` — argv + detach-`Popen` + process helpers (Linux/Windows).
- `core/runtime/` — оркестрация `run_start` / `run_stop` / `run_status`, `RuntimeResult`.
- CLI: `1c-dev runtime start|stop|status` (рядом с существующим `runtime load`).
- MCP: `runtime.start` / `runtime.stop` / `runtime.status` (thin wrappers, ADR-010).

Discovery `1cv8` / `1cv8.exe` и `1cv8c` / `1cv8c.exe` — reuse ADR-005 (+ sibling рядом с `1cv8`).

### Контракт MVP

- Только **file IB** (`runtime.path`, маркер `1Cv8.1CD`) и режим **ENTERPRISE**.
- Клиент: `thick` (`1cv8`) или `thin` (`1cv8c`); default `thick`.
  CLI `--client thick|thin`, MCP `client`.
- Только **detach** (быстрый JSON-ответ; foreground — later).
- Argv: `{1cv8|1cv8c} ENTERPRISE /F<abs-ib> [/Debug]`.
- Состояние: `.runtime/client.pid` (текст pid) + `.runtime/client.meta.json`
  (`mode`, `client`, `debug.enabled`).
- Повторный `start` при живом процессе и **том же** `client` — idempotent (тот же pid).
- Живой процесс с **другим** `client` — `failed` (`1CR004`), suggestion `runtime stop`.
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
| Нет `1cv8` (thick) | `1CR001` | `ENV_UNAVAILABLE` (3) |
| Нет/битый проект / манифест | `1CR002` | `PROJECT_ERROR` (2) |
| Нет file IB (`1Cv8.1CD`) | `1CR003` | `PROJECT_ERROR` (2) |
| Клиент сразу завершился / ошибка процесса / client mismatch | `1CR004` | `RUNTIME_FAILURE` (4) |
| Нет `1cv8c` (thin) | `1CR005` | `ENV_UNAVAILABLE` (3) |

`source` в diagnostics: `"platform"` для discovery; `"runtime"` для product.

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| Detach + pid + `/Debug` flag | Готовый клиент; задел к M6 | GUI нужен на машине | **Принято** |
| `--client thick\|thin` | Явный контракт; расширяемо | Чуть длиннее CLI | **Принято** |
| Только reserved flag без `/Debug` | Меньше argv | Потом всё равно менять launch | Отвергнуто |
| Заглушки MCP `debug.*` сейчас | Видимость API | Шум для агента до DAP | Отвергнуто |
| Foreground start | Проще debug вручную | Блокирует CLI/MCP | Отложено |
| DESIGNER | Шире сценарии | Scope | Отложено |

## Последствия

- README / AGENTS.md / ADR-010: runtime tools с `client` / `--client`.
- Doctor по-прежнему warning без `1cv8`; `runtime.start` thick — жёсткий `1CR001`,
  thin — `1CR005`. Doctor не требует `1cv8c`.
- Client state / pid per runtime path под `.1c-dev/` ([ADR-022](022-project-home.md), [ADR-026](026-runtimes-array.md) Proposed).
- DAP attach к уже запущенному клиенту с `/Debug` — вне активного roadmap (отдельный draft при появлении).

## Связанные решения

- ADR-005, ADR-008, ADR-010, ADR-015, ADR-022, ADR-026 (Proposed)
- PRD §27, §28
- [M4](../milestones/m4-project-model.md)
