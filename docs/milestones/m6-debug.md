# M6: Debug (HTTP Debug Protocol + CLI/MCP)

**Статус:** Planned — документ для нарезки issues; GitHub milestone ещё не создан.  
**ADR:** ADR-030 (создать в фазе 1). Закладка: [ADR-019](../adr/019-runtime-client-lifecycle.md) (`/Debug`, `debug.*` → M6).

## Goal

Единый Debug API в `1c-dev` (CLI + MCP): агент и CI умеют **подключиться к HTTP-серверу отладки 1С**, ставить точки, ждать остановку, читать стек/переменные, вычислять выражения и шагать — без Конфигуратора и без shell.

Продукт остаётся orchestration layer: **не** свой debugger, **не** замена DAP для IDE.  
Lifecycle остаётся прежним: `change → check → build → test → **debug**`.

## Prerequisites

- M1–M5 Done: project home, multi-config/extensions, `runtime.start|stop|status` (+ `--debug` / `/Debug`), Test API
- Платформа 1С 8.3.x с HTTP Debug Server (`dbgs` / эквивалент в составе платформы) и GUI-клиентом
- XML source (`source.format: xml`); EDT — out of scope ([draft-source-formats](draft-source-formats.md))
- File IB + `runtimes[]` (ADR-026); server IB — should / follow-up

## Decisions

| Тема | Решение | Примечание |
|------|---------|------------|
| Backend для агента/CLI | **Прямой HTTP Debug Protocol** → `dbgs` (`POST /e1crdbg/rdbg?cmd=…`) | Как [1c-debug-mcp](https://github.com/liga-1c-command/1c-debug-mcp) (MIT). Не MCP-в-MCP |
| DAP | Protocol-level для **IDE** (человек). Генерация `launch.json` / документация attach — should | [onec-debug-adapter](https://github.com/akpaevj/onec-debug-adapter) / [bsl-debug-server](https://github.com/yukon39/bsl-debug-server) — reuse, не fork в core |
| Platform Tools MCP | Только референс сценариев | IDE-IPC; ломает P1/P2. Не product-путь |
| Поверхность | Свой MCP `debug.*` + CLI `1c-dev debug` | ADR-010 thin wrapper над `core.debug`; без `shell.exec` |
| Свой debugger | **Нет** | PRD §4 non-goal; reuse-first |
| Где живёт HTTP-клиент | `adapters/debug_http/` (XML/HTTP + ping/events) | Core оркестрирует; не парсить stdout CLI |
| Резолв модулей | Index UUID ↔ module из `source.path` (+ extensions) | Референс: metadata cache у 1c-debug-mcp; можно опереться на обход XML / md-reader |
| Сессия | Stateful в процессе CLI/MCP; state на диске под `.1c-dev/` | pid/url/session id; `force_detach` при залипании |
| Lifecycle dbgs | `debug.server start\|stop\|status` (или часть `debug.start`) | Discovery бинаря платформы; host/port из манифеста/флагов |
| Связь с runtime | `runtime.start --debug` уже есть; `debug.attach` ждёт живой dbgs + клиент с `/Debug` | Не дублировать start клиента внутри каждого `debug.*` без явного флага |
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
                      └── ide configure может сгенерировать launch.json (should)
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

Альтернатива (если ADR решит «per-runtime»): поля `debug.*` внутри `runtimes[]` — зафиксировать в ADR-030, не в двух местах сразу.

Paths к CF/CFE **не** дублировать: брать из `configurations[].source` / `extensions[].source`.

## API contract

### Core / CLI / MCP (must)

Один контракт; имена MCP — с точками (как `test.*` / `runtime.*`).

| Операция | CLI (эскиз) | MCP | Core |
|----------|-------------|-----|------|
| Поднять/проверить dbgs | `debug server start\|stop\|status` | `debug.server.start` / `.stop` / `.status` | `core.debug.server_*` |
| Сессия | `debug attach` / `detach` / `force-detach` | `debug.attach` / `debug.detach` / `debug.forceDetach` | session |
| Цели | `debug targets` | `debug.targets` | list targets + metadata ready |
| Breakpoints | `debug breakpoint set\|clear` | `debug.breakpoint` / `debug.clearBreakpoints` | set by moduleName[+extension] / clear |
| Ожидание | `debug wait [--timeout]` | `debug.wait` | wait_for_stop |
| Управление | `debug continue\|step-in\|step-out\|pause` | `debug.continue` / `debug.stepIn` / `debug.stepOut` / `debug.pause` | step actions |
| Инспекция | `debug stack` / `variables` / `eval <expr>` | `debug.stack` / `debug.variables` / `debug.evaluate` | from last stop / targetId |
| Состояние | `debug status` | `debug.status` | session + targets + last stop summary |
| Метаданные index | `debug reload-metadata` | `debug.reloadMetadata` | rebuild UUID↔module cache |

Имена CLI уточнить в ADR-030 (единый стиль с `test` / `runtime`: подкоманды vs флаги).  
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

- `debug.stepOver` (если протокол/адаптер стабильно даёт StepOver)
- `ide configure`: фрагмент launch.json для onec-debug-adapter / bsl-debug-server
- `raw_request` (отладка протокола)
- Doctor capability `debug.http` (dbgs найден, port слушает) — soft gap
- Password / TLS — по необходимости spike

## Scope

### 1. Spike (must, первый шаг)

- Поднять `dbgs`, клиент `runtime.start --debug`, ручной HTTP attach.
- Зафиксировать: argv/discovery `dbgs`, namespace XML cmd’ов, ping/events, autoAttach, setBreakpoints, evalLocalVariables.
- Linux + Windows: где бинарь, нужен ли DISPLAY только клиенту или ещё чему-то.
- Результат → `docs/spikes/NNN-http-debug-protocol.md` (как #119 для YaXUnit). Fixture: минимальный XML-проект + модуль с предсказуемой строкой.

Референс (читать, не копировать в product без лицензионной чистоты MIT + attribution):  
[1c-debug-mcp ARCHITECTURE](https://github.com/liga-1c-command/1c-debug-mcp), [onec-debug-adapter](https://github.com/akpaevj/onec-debug-adapter).

### 2. ADR-030 + schema

- Граница: HTTP adapter vs DAP vs внешние MCP.
- Контракт операций, state layout (`.1c-dev/…`), exit codes, манифест `debug`.
- Решение: ping в том же процессе, что CLI/MCP tool call (как у liga) vs отдельный helper-process — зафиксировать (для stdio MCP обычно in-process + background task).

### 3. Adapter + module index

- `adapters/debug_http/`: client, xml builders/parsers, ping loop, event queue, session.
- Module resolve: `moduleName` + `moduleType` + optional `extensionName` → `objectID`.
- Cache index (mtime invalidate) под `.1c-dev/` или рядом с source — путь в ADR.
- Ограничения: EPF breakpoints не работают; для расширений `extensionName` обязателен при resolve.

### 4. Core + CLI

- `core/debug/`: оркестрация, `DebugResult.to_payload()`, diagnostics codes (`1CD…`).
- CLI `1c-dev debug …`, `--output json|text`, `--config` / `--runtime`.
- Интеграция с уже запущенным `runtime` (читать client.meta `debug.enabled`).

### 5. MCP + DX

- Tools в `mcp_server/tools.py`; descriptions: запрет shell/Designer для этих операций; предупреждение про stateful session.
- `AGENTS.md`: когда предпочитать debug (воспроизводимый runtime failure) vs test.
- `doctor`: soft capability.
- Should: `ide configure` → launch.json hint.

### 6. Acceptance

- Integration E2E: skip без платформы/dbgs/GUI с понятным сообщением.
- Happy path: server → runtime `--debug` → attach → breakpoint → (триггер) → wait → variables/eval → continue → detach.

## Фазы внедрения

| Фаза | Содержание | Результат |
|------|------------|-----------|
| **0. Spike** | Fixture + dbgs + ручной HTTP | Spike-док: cmd’ы, discovery, Linux/Win gaps |
| **1. ADR + schema** | ADR-030, optional `debug` в schema v2 | Замороженный контракт |
| **2. Adapter** | `adapters/debug_http` + module index | Attach/BP/wait/vars/eval на fixture |
| **3. Core + CLI** | `core/debug` + `1c-dev debug` | CI/человек без MCP |
| **4. MCP + DX** | `debug.*`, doctor, AGENTS, opt launch.json | Агент без shell |
| **5. Acceptance** | `tests/test_m6_acceptance.py` | E2E + skip rules |

## Agent workflow (целевой)

```text
build (ИБ актуальна)
  → debug.server.start   # если ещё не поднят
  → runtime.start(debug=true)
  → debug.attach
  → debug.breakpoint(module=…, lines=[…])
  → <действие: UI / вызов / test.run — по сценарию>
  → debug.wait(timeout=…)
  → debug.variables / debug.evaluate
  → правки кода
  → debug.continue | detach
```

Агент **не** держит бесконечный step-loop без цели; prefer короткий сценарий «сломалось на строке N → подтвердить vars → fix».

## Acceptance criteria

### Must

- [ ] Spike-док: HTTP Debug Protocol + discovery `dbgs` (Linux/Windows)
- [ ] ADR-030 Accepted: HTTP facade, граница с DAP / внешними MCP, state, schema
- [ ] Манифест: опциональный `debug` (host/port/alias/autoAttach) валидируется
- [ ] `adapters/debug_http`: attach/detach/forceDetach, targets, breakpoints, wait, continue, stepIn/Out, pause, stack, variables, evaluate
- [ ] Резолв `objectID` из XML source основной conf + extensions; `reloadMetadata`
- [ ] CLI `1c-dev debug …` → structured JSON; ошибки → exit 2/3/4 по ADR-003
- [ ] MCP `debug.*` (полный must-набор таблицы API) без shell.exec
- [ ] Связка с `runtime.start --debug` документирована и покрыта acceptance
- [ ] `force_detach` / recovery при `ibInDebug` или мёртвом ping (поведение из spike → ADR)
- [ ] Doctor: soft gap `debug.http` (или эквивалент)
- [ ] `AGENTS.md`: цикл с debug для runtime failures
- [ ] Integration: `tests/test_m6_acceptance.py`; skip без dbgs/платформы/GUI

### Should

- [ ] `ide configure`: launch.json под внешний DAP-adapter (путь/версия — discovery или docs)
- [ ] `debug.stepOver` если подтверждён протоколом
- [ ] Password через env; не писать секреты в манифест по умолчанию
- [ ] Кэш module index с инвалидацией

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
- Debug UI в Cursor как замена VS Code Debug View (только tools + opt launch.json)
- Conditional BP / logpoints / break-on-error filters — follow-up (есть в onec-debug-adapter; не must M6)
- Автоматический «AI чинит по стеку» без явного сценария пользователя
- Замена `test.*` отладчиком

## Diagnostics (эскиз кодов)

Зафиксировать в ADR-030 (префикс `1CD…`):

| Ситуация | Code (эскиз) | Exit |
|----------|--------------|------|
| Нет / не найден dbgs | `1CD001` | 3 |
| dbgs не отвечает / порт занят не тем | `1CD002` | 4 |
| Нет активной сессии | `1CD003` | 4 |
| Модуль / objectID не резолвится | `1CD004` | 2 или 4 |
| Timeout wait | `1CD005` | 4 |
| Target не в stopped | `1CD006` | 4 |
| Клиент без `/Debug` / нет targets | `1CD007` | 4 |
| Project / manifest | reuse `1CR002` / project codes | 2 |

## Manual verification

```bash
# проект с XML source + file IB после build
1c-dev debug server start --output json
1c-dev runtime start --debug --output json
1c-dev debug attach --output json
1c-dev debug breakpoint set --module ОбщегоНазначения --type CommonModule --lines 42 --output json
# выполнить действие в клиенте, попадающее на строку
1c-dev debug wait --timeout 60000 --output json
1c-dev debug variables --output json
1c-dev debug eval 'Строка(ТекущаяДата())' --output json
1c-dev debug continue --output json
1c-dev debug detach --output json
1c-dev debug server stop --output json
# MCP: тот же сценарий через debug.*
```

## State layout (эскиз)

Под scope / runtime path (уточнить в ADR-030):

```text
.1c-dev/
  runtime/<id>/
    client.pid / client.meta.json   # уже есть; debug.enabled
  debug/
    server.pid                      # если мы стартовали dbgs
    session.json                    # url, alias, sessionId, attachedAt
    modules-cache.json              # UUID ↔ module (opt)
```

## Links

- [Roadmap](../roadmap.md)
- [PRD §28 Debug API](../../1c-dev-runtime-PRD-v0.1.md), [§32 debug tools](../../1c-dev-runtime-PRD-v0.1.md), [§7.9 Debug Adapter](../../1c-dev-runtime-PRD-v0.1.md)
- [ADR-003](../adr/003-diagnostics-exit-codes.md), [ADR-010](../adr/010-mcp-architecture.md), [ADR-019](../adr/019-runtime-client-lifecycle.md), [ADR-026](../adr/026-runtimes-array.md)
- [M4](m4-project-model.md), [M5](m5-tests.md)
- Внешние (референс): [liga-1c-command/1c-debug-mcp](https://github.com/liga-1c-command/1c-debug-mcp) (MIT, agent UX + HTTP), [akpaevj/onec-debug-adapter](https://github.com/akpaevj/onec-debug-adapter) (MIT, DAP), [yukon39/bsl-debug-server](https://github.com/yukon39/bsl-debug-server) (DAP в PRD), [yellow-hammer/mcp-1c-platform-tools](https://github.com/yellow-hammer/mcp-1c-platform-tools/) (не backend)

## Issues (нарезка)

Создать [GitHub milestone M6](https://github.com/pila86/1c-dev/milestones) и issues по таблице. Нумерация — при создании; волны = порядок.

| Wave | Задача | Depends on | Notes |
|------|--------|------------|-------|
| 0 | Spike: HTTP Debug Protocol + discovery `dbgs` (Linux/Win), fixture | M5 Done | → `docs/spikes/…-http-debug-protocol.md` |
| 1 | ADR-030: Debug API (HTTP facade, DAP boundary, state, exit codes) | Wave 0 | |
| 1 | Schema: optional `debug` в `1c.project.schema.v2.json` + validate | ADR-030 | Additive `"2"` |
| 2 | `adapters/debug_http`: client, ping, events, session, XML cmd’ы | Wave 0, ADR | Unit-тесты на builders/parsers с фикстурами XML |
| 2 | Module index: UUID ↔ module (+ extensions), cache, reload | Wave 2 client | |
| 3 | `core/debug`: server lifecycle + attach/BP/wait/step/vars/eval | Adapter | `DebugResult`, codes `1CD…` |
| 3 | CLI `1c-dev debug …` | core | json/text, `--config`/`--runtime` |
| 4 | MCP `debug.*` | core | ADR-010 wrappers |
| 4 | Doctor soft `debug.http` + AGENTS workflow | CLI/MCP | |
| 4 | should: `ide configure` launch.json для внешнего DAP | ADR | |
| 5 | Acceptance E2E `tests/test_m6_acceptance.py` | Waves 3–4 | skip без dbgs/GUI |

### Suggested issue titles (copy-paste)

1. `Spike: HTTP Debug Protocol (dbgs) + fixture`
2. `ADR-030: Debug API (CLI/MCP over HTTP Debug Protocol)`
3. `Schema: optional debug block in project.yaml v2`
4. `adapters/debug_http: session, ping, breakpoints, eval`
5. `debug: module UUID index from XML source + extensions`
6. `core/debug + CLI 1c-dev debug`
7. `MCP debug.* tools`
8. `Doctor debug capability + AGENTS debug workflow`
9. `ide configure: DAP launch.json hint (should)`
10. `Acceptance: M6 debug E2E`

## Риски (коротко)

| Риск | Митигация |
|------|-----------|
| Протокол плохо документирован | Spike + фикстуры XML request/response; MIT-референсы |
| Stateful MCP + долгий wait | Жёсткий timeout; `force_detach`; одна сессия на process |
| GUI / DISPLAY | Как runtime/YAxUnit: документировать; xvfb только если spike подтвердит для debug-клиента |
| Расхождения Linux vs Windows `dbgs` | Spike обязан закрыть оба; иначе Windows-first must + Linux follow-up в ADR |
| Scope creep (logpoints, EDT, Platform Tools) | Out of scope жёстко; should только launch.json |
