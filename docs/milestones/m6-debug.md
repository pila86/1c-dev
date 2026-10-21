# M6: Debug (HTTP Debug Protocol + CLI/MCP)

**Статус:** In progress — [GitHub milestone M6](https://github.com/pila86/1c-dev/milestone/6); PR [#146](https://github.com/pila86/1c-dev/pull/146). Acceptance E2E [#144](https://github.com/pila86/1c-dev/issues/144) (`tests/test_m6_acceptance.py`); осталось `test.* --debug` [#147](https://github.com/pila86/1c-dev/issues/147). `#143` (`ide configure` launch.json) — **вне M6**, follow-up.  
**ADR:** [ADR-031](../adr/031-debug-api-http.md) (Accepted, [#136](https://github.com/pila86/1c-dev/issues/136); ранее в черновике ошибочно «ADR-030» — номер занят Designer `/CheckModules`). Закладка: [ADR-019](../adr/019-runtime-client-lifecycle.md) (`/Debug`, `debug.*` → M6). Spike: [135-http-debug-protocol.md](../spikes/135-http-debug-protocol.md).

## Goal

Единый Debug API в `1c-dev` (CLI + MCP): агент и CI умеют **подключиться к HTTP-серверу отладки 1С**, ставить точки, ждать остановку, читать стек/переменные, вычислять выражения и шагать — без Конфигуратора и без shell.

Продукт остаётся orchestration layer: **не** свой debugger, **не** замена DAP для IDE.  
Lifecycle остаётся прежним: `change → build → check → test → **debug**`.

## Prerequisites

- M1–M5 Done: project home, multi-config/extensions, `runtime.start|stop|status` (+ `--debug` / `/Debug`), Test API
- Платформа 1С 8.3.x с HTTP Debug Server (`dbgs` / эквивалент в составе платформы) и GUI-клиентом
- XML source (`source.format: xml`); EDT — out of scope ([draft-source-formats](draft-source-formats.md))
- File IB + `runtimes[]` (ADR-026); server IB — should / follow-up

## Decisions

| Тема | Решение | Примечание |
|------|---------|------------|
| Backend для агента/CLI | **Прямой HTTP Debug Protocol** → `dbgs` (`POST /e1crdbg/rdbg?cmd=…`) | Как [1c-debug-mcp](https://github.com/liga-1c-command/1c-debug-mcp) (MIT). Не MCP-в-MCP |
| DAP | Protocol-level для **IDE** (человек). Reuse внешних adapter’ов; генерация `launch.json` — **вне M6** ([#143](https://github.com/pila86/1c-dev/issues/143) follow-up) | [onec-debug-adapter](https://github.com/akpaevj/onec-debug-adapter) / [bsl-debug-server](https://github.com/yukon39/bsl-debug-server) — не fork в core |
| Platform Tools MCP | Только референс сценариев | IDE-IPC; ломает P1/P2. Не product-путь |
| Поверхность | Свой MCP `debug.*` + CLI `1c-dev debug` | ADR-010 thin wrapper над `core.debug`; без `shell.exec` |
| Свой debugger | **Нет** | PRD §4 non-goal; reuse-first |
| Где живёт HTTP-клиент | `adapters/debug_http/` (XML/HTTP + ping/events) | Core оркестрирует; не парсить stdout CLI |
| Резолв модулей | Index UUID ↔ module из `source.path` (+ extensions) | Референс: metadata cache у 1c-debug-mcp; можно опереться на обход XML / md-reader |
| Сессия | Stateful в процессе CLI/MCP; state на диске под `.1c-dev/` | pid/url/session id; `force_detach` при залипании |
| Lifecycle dbgs | `debug.server start\|stop\|status` (или часть `debug.start`) | Discovery бинаря платформы; host/port из манифеста/флагов |
| Связь с runtime | `runtime.start --debug` уже есть; `debug.attach` ждёт живой dbgs + клиент с `/Debug` | Не дублировать start клиента внутри каждого `debug.*` без явного флага |
| Связь с test | `test.run --debug [--bp]` / `test.wait` (#147) | Non-blocking как runtime; stop → `debug.wait`; jUnit → `test.wait` |
| Выбор ИБ / config | `--config` / `--runtime` как в test/build | Default = default runtime выбранной config |
| Exit codes | Ошибки сессии/окружения → `RUNTIME_FAILURE` (4); project → 2; env (нет dbgs) → 3 | Новый код не вводить без ADR-003 amendment |
| Schema | Additive в schema `"2"`: опциональный блок `debug` (host/port/alias/autoAttach) | Bump major не нужен, если только optional |
| `raw_request` | Should / opt-in; default off в MCP descriptions | Escape hatch; не основной путь агента |
| EPF breakpoints | Не must | Ограничение протокола 1С; документировать `pause` + step |

### Почему не vendor 1c-debug-mcp / не DAP-first для агента

- **Отдельный MCP** рядом с `1c-dev mcp` — два оркестратора, два конфига, пересечение с `runtime.*` / путями проекта.
- **DAP** — event-driven, неудобен как набор MCP tools; агенту нужен request/response + явный `wait_for_stop(timeout)`.
- **Reuse механики** (XML cmd’ы, ping 500ms, autoAttach, metadata resolve) — да; **product facade** — свой, в одном контракте CLI+MCP.

### Два фасада (не смешивать в одном tool)

```text
Agent / CLI  ──►  core.debug.*  ──►  adapters/debug_http  ──►  dbgs (HTTP)
IDE (человек) ──►  DAP (внешний adapter)  ──►  dbgs (HTTP)
                      ▲
                      └── ide configure → launch.json — follow-up (#143), не M6
```

## Эскиз манифеста

```yaml
# schema "2" additive — опциональный блок
debug:
  host: localhost
  port: 1550
  # alias ИБ на debug-сервере (file IB часто DefAlias)
  infobaseAlias: DefAlias
  # типы auto-attach (имена как у платформы / onec-debug-adapter)
  autoAttachTypes: [Client, ManagedClient, Server, ServerEmulation]
  # password: опционально; лучше env ONEC_DEBUG_PASSWORD, не в git
```

**Решение ADR-031:** top-level `debug` (не per-runtime в `runtimes[]`). Поля `debug.*` внутри `runtimes[]` не вводятся.

Paths к CF/CFE **не** дублировать: брать из `configurations[].source` / `extensions[].source`.

## API contract

### Core / CLI / MCP (must)

Один контракт; имена MCP — с точками (как `test.*` / `runtime.*`).

| Операция | CLI (эскиз) | MCP | Core |
|----------|-------------|-----|------|
| Поднять/проверить dbgs | `debug server start\|stop\|status` | `debug.server.start` / `.stop` / `.status` | `core.debug.server_*` |
| Сессия | `debug attach` / `detach` / `force-detach` | `debug.attach` / `debug.detach` / `debug.forceDetach` | session |
| Цели | `debug targets` | `debug.targets` | list targets + metadata ready |
| Breakpoints | `debug breakpoint set\|clear` | `debug.breakpoint` / `debug.clearBreakpoints` | set by moduleName / `--file` path / clear |
| Ожидание | `debug wait [--timeout] [--fresh]` | `debug.wait` | по состоянию: мгновенно, если stop уже записан; `--fresh` — следующий стоп; `1CD016` если runtime/test pid мертвы; после `test.run* --debug` — `fresh=false` |
| Управление | `debug continue\|step-in\|step-over\|step-out\|pause` | `debug.continue` / `debug.stepIn` / `debug.stepOver` / `debug.stepOut` / `debug.pause` | `continue`, `step-in/over/out` — поддерживаются (live acceptance); **`pause` — experimental**; выход клиента во время шага → `ok` + warning `1CD016` |
| Инспекция | `debug stack` / `variables` / `eval <expr>` | `debug.stack` / `debug.variables` / `debug.evaluate` | from last stop / targetId |
| Состояние | `debug status` | `debug.status` | session + targets + last stop summary |
| Метаданные index | `debug reload-metadata` | `debug.reloadMetadata` | rebuild UUID↔module cache |

Имена CLI зафиксированы в [ADR-031](../adr/031-debug-api-http.md) (подкоманды, стиль `test` / `runtime`).  
PRD §28 (`debug.start` / `debug.stop`) мапится так: **start** = server ensure + attach (+ opt `runtime.start --debug`); **stop** = detach (+ opt server stop).

### Payload (эскиз)

Все команды: structured JSON (`status`, `diagnostics[]`, `duration`, поля результата).  
`wait` / stop-event:

```json
{
  "status": "ok",
  "targetId": "…",
  "moduleName": "CommonModule.ОбщегоНазначения",
  "lineNo": 42,
  "callStack": [{"moduleName": "…", "lineNo": 42}],
  "diagnostics": []
}
```

Таймаут `wait` без остановки → `status: failed` + diagnostic (не hang навечно). Default timeout зафиксировать в ADR (например 30s), CLI/MCP override.

### Should (не блокеры acceptance)

- `raw_request` (отладка протокола)
- Doctor capability `debug.http` (dbgs найден, port слушает) — soft gap — DONE (#142)
- Password / TLS — по необходимости spike

`ide configure` → launch.json ([#143](https://github.com/pila86/1c-dev/issues/143)) — **не в scope M6** (follow-up / backlog).

## Scope

### 1. Spike (must, первый шаг)

- Поднять `dbgs`, клиент `runtime.start --debug`, ручной HTTP attach.
- Зафиксировать: argv/discovery `dbgs`, namespace XML cmd’ов, ping/events, autoAttach, setBreakpoints, evalLocalVariables.
- Linux + Windows: где бинарь, нужен ли DISPLAY только клиенту или ещё чему-то.
- Результат → `docs/spikes/NNN-http-debug-protocol.md` (как #119 для YaXUnit). Fixture: минимальный XML-проект + модуль с предсказуемой строкой.

Референс (читать, не копировать в product без лицензионной чистоты MIT + attribution):  
[1c-debug-mcp ARCHITECTURE](https://github.com/liga-1c-command/1c-debug-mcp), [onec-debug-adapter](https://github.com/akpaevj/onec-debug-adapter).

### 2. ADR-031 + schema

- Граница: HTTP adapter vs DAP vs внешние MCP — [ADR-031](../adr/031-debug-api-http.md) Accepted.
- Контракт операций, state layout (`.1c-dev/debug/…`), exit codes, top-level `debug`.
- Ping: in-process ~500 ms (helper-process отвергнут). Schema validate — [#137](https://github.com/pila86/1c-dev/issues/137).

### 3. Adapter + module index

- `adapters/debug_http/`: client, xml builders/parsers, ping loop, event queue, session.
- Module resolve: `moduleName` + `moduleType` + optional `extensionName` → `objectID`.
- Cache index (mtime invalidate): `.1c-dev/debug/modules-cache.json` (ADR-031).
- Ограничения: EPF breakpoints не работают; для расширений `extensionName` обязателен при resolve.

### 4. Core + CLI

- `core/debug/`: оркестрация, `DebugResult.to_payload()`, diagnostics codes (`1CD…`).
- CLI `1c-dev debug …`, `--output json|text`, `--config` / `--runtime`.
- Интеграция с уже запущенным `runtime` (читать client.meta `debug.enabled`).

### 5. MCP + DX

- Tools в `mcp_server/tools.py`; descriptions: запрет shell/Designer для этих операций; предупреждение про stateful session.
- `AGENTS.md`: когда предпочитать debug (воспроизводимый runtime failure) vs test.
- `doctor`: soft capability.

### 6. Acceptance

- Integration E2E: skip без платформы/dbgs/GUI с понятным сообщением.
- Happy path: server → runtime `--debug` → attach → breakpoint → (триггер) → wait → variables/eval → continue → detach.

## Фазы внедрения

| Фаза | Содержание | Результат |
|------|------------|-----------|
| **0. Spike** | Fixture + dbgs + ручной HTTP | Spike-док: cmd’ы, discovery, Linux/Win gaps |
| **1. ADR + schema** | ADR-031 Accepted; optional `debug` в schema v2 (#137) | Замороженный контракт |
| **2. Adapter** | `adapters/debug_http` + module index | Attach/BP/wait/vars/eval на fixture |
| **3. Core + CLI** | `core/debug` + `1c-dev debug` | CI/человек без MCP |
| **4. MCP + DX** | `debug.*`, doctor, AGENTS | Агент без shell |
| **5. Acceptance** | `tests/test_m6_acceptance.py` | E2E + skip rules |

## Agent workflow (целевой)

```text
build (ИБ актуальна)
  → runtime.start(debug=true, breakpoints=[…])  # ensure dbgs + attach + BP
  → <действие: UI / вызов>
  → debug.wait(timeout=…)
  → debug.variables / debug.evaluate
  → правки кода
  → debug.continue
  → runtime.stop   # teardown debug; явный detach часто 1CD003 — ок
```

Stepwise (advanced): `debug.server.start` → `attach` → `breakpoint` →
`runtime.start(debug=true)` → `debug.wait` → …

Агент **не** держит бесконечный step-loop без цели; prefer короткий сценарий «сломалось на строке N → подтвердить vars → fix».

**Отладка упавшего теста** (симметрия с runtime, #147):

```text
test.run(debug=true, breakpoints=[…])   # status: running + pid; не ждёт stop / exit
  → debug.wait → variables / eval → continue …
  → test.wait                            # exit 1cv8 → jUnit → teardown debug (как runtime.stop)
```

## Acceptance criteria

### Must

- [x] Spike-док: HTTP Debug Protocol + discovery `dbgs` (Linux live; Windows — docs/gaps) — [#135](https://github.com/pila86/1c-dev/issues/135) / [spike](../spikes/135-http-debug-protocol.md)
- [x] ADR-031 Accepted: HTTP facade, граница с DAP / внешними MCP, state, schema — [#136](https://github.com/pila86/1c-dev/issues/136) / [ADR-031](../adr/031-debug-api-http.md)
- [x] Манифест: опциональный `debug` (host/port/alias/autoAttach) валидируется — [#137](https://github.com/pila86/1c-dev/issues/137)
- [x] `adapters/debug_http`: attach/detach/forceDetach, targets, breakpoints, wait, continue, stepIn/Out, pause, stack, variables, evaluate — [#138](https://github.com/pila86/1c-dev/issues/138)
- [x] Резолв `objectID` из XML source основной conf + extensions; `reloadMetadata` — [#139](https://github.com/pila86/1c-dev/issues/139)
- [x] CLI `1c-dev debug …` → structured JSON; ошибки → exit 2/3/4 по ADR-003 — [#140](https://github.com/pila86/1c-dev/issues/140)
- [x] BP по пути `.bsl` (`--file`) + ObjectModule/ManagerModule propertyID — [#145](https://github.com/pila86/1c-dev/issues/145)
- [x] MCP `debug.*` (полный must-набор таблицы API) без shell.exec (#141)
- [x] Связка с `runtime.start --debug` документирована (AGENTS / #142); acceptance E2E — [#144](https://github.com/pila86/1c-dev/issues/144)
- [x] `force_detach` / recovery при `ibInDebug` или мёртвом ping — поведение зафиксировано в ADR-031
- [x] Doctor: soft gap `debug.http` (dbgs + listening probe) — [#142](https://github.com/pila86/1c-dev/issues/142)
- [x] `AGENTS.md`: цикл с debug для runtime failures — [#142](https://github.com/pila86/1c-dev/issues/142)
- [x] Integration: `tests/test_m6_acceptance.py` (core + CLI + MCP); skip без dbgs/платформы/GUI — [#144](https://github.com/pila86/1c-dev/issues/144)
- [x] `test.run` / `test.runOne` `--debug` / `--bp` (non-blocking) + `test.wait` / MCP; reuse `ensure_debug_for_runtime` — [#147](https://github.com/pila86/1c-dev/issues/147)

### Should

- [x] `debug.stepOver` (CLI `step-over`, platform `Step`) — [#140](https://github.com/pila86/1c-dev/issues/140)
- [x] `debug.stepIn` / `stepOver` / `stepOut` стабильны (CLI; live acceptance `test_m6_acceptance_steps_cli`: 3 прогона подряд + расширение)
- [ ] `debug.pause` стабилен (сейчас experimental, live acceptance не пройден)
- [x] Password через env `ONEC_DEBUG_PASSWORD`; в манифест не пишется (schema отвергает), маскируется в ошибках — [ADR-031 §2a](../adr/031-debug-api-http.md)
- [x] Кэш module index с инвалидацией (mtime) — [#139](https://github.com/pila86/1c-dev/issues/139)
- [x] `breakpoint set --file` / `--object-id`+`--property-id` (escape) — [#145](https://github.com/pila86/1c-dev/issues/145)

### Nice

- [ ] `raw_request` за флагом/отдельным tool
- [ ] Server IB / remote dbgs host
- [ ] Авто-`runtime.start --debug` внутри `debug.start` (явный флаг, не silent)

## Out of scope

- Собственный debugger / свой DAP-server с нуля
- Vendor / зависимость runtime от [mcp-1c-platform-tools](https://github.com/yellow-hammer/mcp-1c-platform-tools/) или второго MCP `1c-debug-mcp` как обязательного компонента
- EDT source / `source.convert` ([draft-source-formats](draft-source-formats.md))
- Semantic diff / impact / verify
- Remote / Docker / lockfile (отдельный draft)
- Debug UI в Cursor как замена VS Code Debug View
- `ide configure` → DAP `launch.json` hint — follow-up [#143](https://github.com/pila86/1c-dev/issues/143) (вне M6)
- Conditional BP / logpoints / break-on-error filters — follow-up (есть в onec-debug-adapter; не must M6)
- Автоматический «AI чинит по стеку» без явного сценария пользователя
- Замена `test.*` отладчиком

## Diagnostics (эскиз кодов)

Зафиксировано в [ADR-031](../adr/031-debug-api-http.md) (префикс `1CD…`):

| Ситуация | Code (эскиз) | Exit |
|----------|--------------|------|
| Нет / не найден dbgs | `1CD001` | 3 |
| dbgs не отвечает / порт занят не тем | `1CD002` | 4 |
| Нет активной сессии | `1CD003` | 4 |
| Модуль / objectID не резолвится | `1CD004` | 2 или 4 |
| Timeout wait | `1CD005` | 4 |
| Клиент завершился без остановки | `1CD016` | 4 |
| Target не в stopped | `1CD006` | 4 |
| Клиент без `/Debug` / нет targets | `1CD007` | 4 |
| Project / manifest | reuse `1CR002` / project codes | 2 |

## Manual verification

```bash
# Сценарий: runtime start с breakpoints → смотрим переменные → continue → stop.
# Лучше во *внешнем* терминале (не integrated): толстый 1cv8 на том же DISPLAY
# что IDE на BP может подвиснуть весь GUI до continue / выхода клиента.
1c-dev runtime start --debug \
  --bp src/main/Ext/ManagedApplicationModule.bsl:4 \
  --bp 'src/main/CommonModules/ОтладкаДемо/Ext/Module.bsl:8' \
  --output json                      # не ждёт остановку: dbgs → attach → BP → spawn → arm
1c-dev debug wait --timeout 30 --output json      # сразу вернётся, если уже стоим на BP
1c-dev debug stack --output json
1c-dev debug variables --output json
1c-dev debug eval 'Строка(ИмяСценария)' --output json
1c-dev debug continue --output json               # ждёт следующий BP
1c-dev debug variables --output json
1c-dev debug continue --no-wait --output json     # последний continue
1c-dev runtime stop --output json                 # клиент + демон + detach + наш dbgs

# пошаговый вариант (без --bp):
# 1c-dev debug server start → attach → breakpoint set --file … → runtime start --debug → wait …
# step-in/over/out — шаги после остановки; pause — experimental.
# MCP: тот же сценарий через debug.*
```

## State layout (эскиз)

Под `.1c-dev/` (зафиксировано в ADR-031): debug — project-scoped; client — per-runtime:

```text
.1c-dev/
  runtime/<id>/
    client.pid / client.meta.json   # уже есть; debug.enabled + debuggerUrl (M6)
  debug/
    server.pid / server.meta.json   # если мы стартовали dbgs
    session.json                    # url, alias, sessionId, attachedAt
    modules-cache.json              # UUID ↔ module
```

## Links

- [Roadmap](../roadmap.md)
- [PRD §28 Debug API](../../1c-dev-runtime-PRD-v0.1.md), [§32 debug tools](../../1c-dev-runtime-PRD-v0.1.md), [§7.9 Debug Adapter](../../1c-dev-runtime-PRD-v0.1.md)
- [ADR-003](../adr/003-diagnostics-exit-codes.md), [ADR-010](../adr/010-mcp-architecture.md), [ADR-019](../adr/019-runtime-client-lifecycle.md), [ADR-026](../adr/026-runtimes-array.md), [ADR-031](../adr/031-debug-api-http.md)
- [M4](m4-project-model.md), [M5](m5-tests.md)
- Внешние (референс): [liga-1c-command/1c-debug-mcp](https://github.com/liga-1c-command/1c-debug-mcp) (MIT, agent UX + HTTP), [akpaevj/onec-debug-adapter](https://github.com/akpaevj/onec-debug-adapter) (MIT, DAP), [yukon39/bsl-debug-server](https://github.com/yukon39/bsl-debug-server) (DAP в PRD), [yellow-hammer/mcp-1c-platform-tools](https://github.com/yellow-hammer/mcp-1c-platform-tools/) (не backend)

## Issues

[GitHub milestone M6](https://github.com/pila86/1c-dev/milestone/6). Волны = порядок.

| # | Wave | Задача | Depends on | Status |
|---|------|--------|------------|--------|
| [#135](https://github.com/pila86/1c-dev/issues/135) | 0 | Spike: HTTP Debug Protocol (dbgs) + fixture | M5 Done | DONE ([spike](../spikes/135-http-debug-protocol.md)) |
| [#136](https://github.com/pila86/1c-dev/issues/136) | 1 | ADR-031: Debug API (CLI/MCP over HTTP Debug Protocol) | #135 | DONE ([ADR-031](../adr/031-debug-api-http.md)) |
| [#137](https://github.com/pila86/1c-dev/issues/137) | 1 | Schema: optional `debug` в project.yaml v2 | #136 | DONE |
| [#138](https://github.com/pila86/1c-dev/issues/138) | 2 | `adapters/debug_http`: session, ping, breakpoints, eval | #135, #136 | DONE |
| [#139](https://github.com/pila86/1c-dev/issues/139) | 2 | Module UUID index from XML source + extensions | #138 | DONE |
| [#140](https://github.com/pila86/1c-dev/issues/140) | 3 | `core/debug` + CLI `1c-dev debug` | #137–#139 | DONE |
| [#145](https://github.com/pila86/1c-dev/issues/145) | 2.5 | `breakpoint set --file` (ObjectModule / path → objectID) | #138–#140 | DONE |
| [#141](https://github.com/pila86/1c-dev/issues/141) | 4 | MCP `debug.*` tools | #140 | DONE |
| [#142](https://github.com/pila86/1c-dev/issues/142) | 4 | Doctor `debug.http` + AGENTS debug workflow | #140, #141 | DONE |
| [#144](https://github.com/pila86/1c-dev/issues/144) | 5 | Acceptance: M6 debug E2E | #140–#142 | DONE (`tests/test_m6_acceptance.py`) |
| [#147](https://github.com/pila86/1c-dev/issues/147) | 5.5 | `test.run --debug/--bp` + `test.wait` (симметрия с runtime) | #140, #144 | DONE (в PR #146) |

Вне milestone: [#143](https://github.com/pila86/1c-dev/issues/143) (`ide configure` DAP launch.json) — follow-up / backlog.

## Риски (коротко)

| Риск | Митигация |
|------|-----------|
| Протокол плохо документирован | Spike + фикстуры XML request/response; MIT-референсы |
| Stateful MCP + долгий wait | Жёсткий timeout; `force_detach`; одна сессия на process |
| GUI / DISPLAY | Как runtime/YAxUnit: документировать; xvfb только если spike подтвердит для debug-клиента |
| Расхождения Linux vs Windows `dbgs` | Spike обязан закрыть оба; иначе Windows-first must + Linux follow-up в ADR |
| Scope creep (logpoints, EDT, Platform Tools, launch.json) | Out of scope жёстко; `#143` вынесен из M6 |
