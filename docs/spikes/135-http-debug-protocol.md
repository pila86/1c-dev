# Spike #135: HTTP Debug Protocol (dbgs) + fixture

**Дата:** 2026-10-12  
**Платформа:** 8.3.25.1560 (Linux x86_64, `/opt/1cv8/x86_64/8.3.25.1560/`)  
**Issue:** [#135](https://github.com/pila86/1c-dev/issues/135)  
**Граница:** discovery/argv `dbgs`, HTTP cmd’ы, клиент `/Debug -http`, ping/events, BP/eval, recovery.  
Контракт Debug API — **ADR-031** ([#136](https://github.com/pila86/1c-dev/issues/136)). Продуктового кода нет.  
**Важно:** в [m6-debug.md](../milestones/m6-debug.md) ошибочно указан «ADR-030» — номер уже занят ([030-designer-check-modules.md](../adr/030-designer-check-modules.md)). Debug API = **ADR-031**.

Fixture: [tests/fixtures/debug_spike/](../../tests/fixtures/debug_spike/README.md) (XML-проект + `run_http_debug.py` — прототип).

## TL;DR для ADR-031

| Вопрос | Ответ |
|--------|-------|
| Бинарь | Sibling рядом с `1cv8`/`ibcmd`: Linux `…/8.3.x.y/dbgs`; Windows `…\bin\dbgs.exe` (из docs; live не проверялся) |
| Argv `dbgs` | `--addr=<host> --port=<port>` (**порт обязателен**, default нет). Опц.: `--notify=<file>` (UTF-16 LE!), `--daemon`, `--password`, `--ownerPID`, `--portRange` |
| Порт | **Не хардкодить 1550.** На dev-машине spike: `1540/1541/1550/1560` заняты `ragent`/`dbgs` кластера. Стратегия: манифест `debug.port` / CLI / `--portRange` вне служебных + `--notify` |
| Клиент HTTP | `1cv8 ENTERPRISE /F<ib> /Debug -http -attach /DebuggerURL"http://host:port"` |
| Клиент только `/Debug` | **Не** регистрируется на HTTP `dbgs` (targets пустой). Product `runtime.start --debug` сейчас недостаточен для M6 |
| Alias file IB | `DefAlias` (неизменяемый) |
| HTTP | `POST {url}/e1crdbg/rdbg?cmd=<name>`, `Content-Type: application/xml`, `User-Agent: 1CV8` |
| Ping | `POST …?cmd=pingDebugUIParams&dbgui=<sessionId>` — **без тела** |
| Attach result | успех = `registered`; конфликт = `ibInDebug` → detach + retry |
| Eval | на 8.3.25.1560 результат **синхронно в теле ответа** POST (`evalResultState=correctly`); ping `exprEvaluated` за 15с **не** наблюдали |
| BP | `objectID` + `propertyID` + **исполняемая** строка (голый комментарий не ловит). Стек: последний кадр = место остановки |
| Ping loop | in-process, ~500 ms (достаточно для CLI/MCP stdio) |
| DISPLAY | нужен **только клиенту**; `dbgs` без GUI |
| `force_detach` | локально: `detachDebugUI` + очистить session id; при `ibInDebug` — detach + AttachWithRetry (до 5) |

## 1. Окружение

- Linux x86_64, `DISPLAY=:0` (живой GUI, не xvfb).
- Параллельно крутится кластер 8.3.25.1445 с `-debug -http` и своим `dbgs --port=1550` (пользователь `usr1cv8`) — поэтому spike использовал порт **2550**.
- File IB после `1c-dev build` на копии fixture (~1.3–2.5 с).

### Discovery (рекомендация в продукт)

Сейчас [`adapters/platform/discovery.py`](../../adapters/platform/discovery.py) **не** знает `dbgs`. Паттерн как у `ibsrv`/`1cv8c`: `_tool_from_installs("dbgs")` + sibling рядом с найденным `1cv8`/`ibcmd`.

| ОС | Путь (проверено / docs) |
|----|-------------------------|
| Linux | `/opt/1cv8/x86_64/<ver>/dbgs` — **проверено** (8.3.23.1739, 8.3.25.1445, 8.3.25.1560) |
| Windows | `%PROGRAMFILES%\1cv8\<ver>\bin\dbgs.exe` — по админ-гайду / MIT-референсам, **не live** |

## 2. Argv `dbgs` (проверено)

```text
dbgs --addr=localhost --port=2550 --notify=/tmp/dbgs.notify
```

| Флаг | Наблюдение |
|------|------------|
| `--port` | Обязателен; без него help, сервер не слушает «default 1550» |
| `--notify` | Файл с `host:port` в **UTF-16 LE** (BOM `FF FE`) |
| `--daemon` | Есть в help (Linux); в spike не включали |
| `--password` | Есть; без пароля attach без `<credentials>` ок |

Лог старта: `Debug Server started. Ctrl+C to exit.`

## 3. Argv клиента (проверено)

### HTTP (must для M6)

```text
1cv8 ENTERPRISE /F</abs/ib> /Debug -http -attach /DebuggerURL"http://localhost:2550"
```

- Target type: `Client`, alias `DefAlias`, state `Worked` → после attachDetach — управление.
- `targetStarted` приходит в ping после старта клиента.

### Только `/Debug` (текущий product)

```text
1cv8 ENTERPRISE /F</abs/ib> /Debug
```

- Attach debugger UI к нашему `dbgs` успешен (`registered`).
- `getDbgAllTargetStates` → **пустой** `<response/>`; `targetStarted` **нет**.
- **Вывод для ADR-031:** расширить `runtime.start --debug` до `/Debug -http -attach` + `/DebuggerURL` (URL из манифеста/`debug.server`), либо отдельный флаг / связка `debug.attach` → ensure client argv.

## 4. HTTP cmd’ы и namespaces

Базовый URL: `http://host:port`. Test: `POST /e1crdbg/rdbgTest?cmd=test`.

Namespaces (MIT-референс [1c-debug-mcp](https://github.com/liga-1c-command/1c-debug-mcp) `xmlproto`, подтверждены ответами платформы):

| Prefix | URI |
|--------|-----|
| request/response | `http://v8.1c.ru/8.3/debugger/debugRDBGRequestResponse` |
| base | `…/debugBaseData` |
| breakpoints | `…/debugBreakpoints` |
| calculations | `…/debugCalculations` |
| autoAttach | `…/debugAutoAttach` |

| cmd | Тело | Наблюдение |
|-----|------|------------|
| `attachDebugUI` | alias + idOfDebuggerUI + options | result `registered` |
| `detachDebugUI` | alias + id | result `1` |
| `initSettings` | `breakOnNextLine` true/false | pause / сброс pause |
| `setAutoAttachSettings` | типы `Client`, `ManagedClient`, `Server`, `ServerEmulation` | http 200 |
| `setBreakpoints` | bpWorkspace: objectID+propertyID+lines | http 200; переотправлять после attach target |
| `attachDetachDbgTargets` | `<attach>true</attach>` + target id | после `targetStarted` |
| `pingDebugUIParams` | **пусто**, query `dbgui=` | events: `targetStarted`, `callStackFormed` |
| `getDbgAllTargetStates` | alias + id | список целей |
| `evalLocalVariables` | targetID + expr/context | **sync** result в POST |
| `evalExpr` | expression + resultID | **sync** result в POST |
| `step` | action `Continue` / `StepIn` / `StepOut` | Continue проверен |

Шаблоны XML — в прототипе [`run_http_debug.py`](../../tests/fixtures/debug_spike/run_http_debug.py) (по мотивам MIT 1c-debug-mcp; в product — attribution + своя реализация в `adapters/debug_http`).

## 5. Сессия, ping, stop

1. `uuid4` → `idOfDebuggerUI`.
2. `attachDebugUI` → `registered`.
3. `initSettings(false)` → `setAutoAttachSettings` → `setBreakpoints`.
4. Старт клиента с DebuggerURL.
5. Ping ~500 ms: `targetStarted` → `attachDetachDbgTargets` → **снова** `setBreakpoints`.
6. `callStackFormed` → stop. В стеке несколько кадров; **текущий** = последний `objectID`/`lineNo`.
7. Eval / step / `detachDebugUI`.

Fixture: без busy-wait в `ПриНачалеРаботыСистемы` — BP до spawn + poll targets
(`runtime start --debug --bp`). ApplicationModule BP: строка вызова `ВыполнитьДемо`.

### 5a. `pingDebugUIParams` — long-poll (замер, рефакторинг M6)

Сырой замер на 8.3.25.1560, один читатель ping, клиент остановлен на BP:

| Ситуация | Результат |
|----------|-----------|
| Ping без событий | HTTP **204**, пустое тело, ответ приходит через **≈5.0 s** (сервер держит запрос) |
| `step` (`Step` / `StepIn`) | HTTP 200, в теле `<state>Worked</state>`; следом ping отдаёт событие (смена state), через ≈1 s второй ping — `callStackFormed` |
| Ping с client timeout 2 s | Запрос обрывается клиентом **до** ответа сервера |

Вывод: события в ping отдаются **один раз** и привязаны к конкретному запросу. Ping с
client timeout короче серверного long-poll (5 s) — это (а) постоянные «таймауты» на
простое и (б) **потеря событий**: сервер уже снял событие из очереди и отдал его в
закрытое соединение. Прежний `ping_worker` / in-process ping использовали timeout 2 s и
считали такие таймауты ошибками (после 20 подряд воркер завершался), параллельно с
`HotDebugArm` читал ping второй читатель.

Контракт нового механизма:

- ping-запрос с timeout **≥ 10 s** (> 5 s long-poll); таймаут не считается ошибкой;
- единственный читатель ping — фоновый демон (`core.debug.ping_worker`);
- attach target (`attachDetachDbgTargets` + `setBreakpoints`) делает демон один раз на
  target; повторный attach **остановленного** target ломает step (проверено на StepIn);
- CLI-команды ping не вызывают, а читают `lastStop` / `attachedTargets` из `session.json`.

### propertyID (канон типов модулей)

| Модуль | propertyID |
|--------|------------|
| CommonModule (SimpleModule) | `d5963243-262e-4398-b4d7-fb16d06484f6` |
| ApplicationModule (Managed) | `d22e852a-cf8a-4f77-8ccb-3548e7792bea` |
| ObjectModule | `a637f77f-3840-441d-a1c3-699c8c5cb7e0` |
| ManagerModule | `d1b64a2c-8078-4982-8190-8f81aefda192` |
| FormModule | `32e087ab-1491-49b6-aba7-43571b41ac2b` |
| RecordSetModule | `9f36fd70-4bf4-47f6-b235-935f73aab43f` |

Источник: go1cover `metaDataObjects.go` / MIT ModulePropertyID; Common+Application подтверждены spike stop-event’ом; ObjectModule+ — [#145](https://github.com/pila86/1c-dev/issues/145).

## 6. Breakpoints / eval (fixture)

| Модуль | objectID | line | Результат |
|--------|----------|------|-----------|
| `ОтладкаДемо` | `b7e2c4a1-8f3d-4a6e-9c1b-2d5e8f0a3b6c` | 5 (`Значение = 42; // BP-LINE`) | Stop; стек: App:9 → Common:5 |
| ManagedApplicationModule | Configuration uuid | 9 (вызов демо) | Stop без pause |
| Голый `// BP-LINE` на отдельной строке | — | — | **не** ловит; ставить на исполняемую |

`evalLocalVariables` на CommonModule BP (до исполнения строки): `Значение`/`Результат` = `Неопределено` (остановка **перед** строкой).  
`evalExpr` / locals на ApplicationModule: локаль `Конец` (Число) — `evalResultState=correctly`.  
`pres` в ответе — base64.

**Pause:** `initSettings(breakOnNextLine=true)` — надёжный smoke без module BP; после stop сбрасывать в `false`.

## 7. Recovery / force_detach

| Сценарий | Поведение |
|----------|-----------|
| Повторный attach той же ИБ другим id | `ibInDebug` → `detachDebugUI` + retry (как AttachWithRetry) |
| `force_detach` | detach текущей сессии + новый session id; проверено: zombie attach → force_detach → attach `registered` → happy path |
| Ping HTTP 400 | в референсе: dbgs перезапущен → detach/reattach/restore BP; на spike искусственно не ломали dbgs mid-flight |
| Мёртвый клиент | targets пропадают; detach UI всё равно успешен |

## 8. Linux / Windows gaps

| Тема | Linux (spike) | Windows |
|------|---------------|---------|
| Бинарь | `dbgs` без `.exe` | `dbgs.exe` в `bin\` (docs) |
| `--daemon` | есть | service-режим в docs |
| `--notify` encoding | UTF-16 LE | **не проверено** (ожидать UTF-16) |
| DISPLAY / GUI | клиенту нужен X | GUI сессия пользователя |
| Argv `/DebuggerURL"…"` | работает | docs: тот же канон; кавычки cmd.exe — осторожно |
| Live E2E | **да** (8.3.25.1560) | **нет** → follow-up в ADR или CI win |

## 9. Находки по текущему продукту

1. [`build_enterprise_argv`](../../adapters/platform_1cv8/process.py): `--debug` → только `/Debug` — **не** HTTP. Нужно расширение в M6 (ADR-031 / runtime follow-up).
2. Discovery без `dbgs` — добавить sibling-tool.
3. Default port `1550` в эскизе манифеста m6 опасен на машинах с кластером — default лучше «не задан» / `portRange` / doctor warning.
4. Номер ADR в m6/#136: заменить 030 → **031**.

## 10. Референсы (reuse механики, не vendor)

- [liga-1c-command/1c-debug-mcp](https://github.com/liga-1c-command/1c-debug-mcp) (MIT) — XML builders, ping 500 ms, autoAttach, metadata resolve.
- [akpaevj/onec-debug-adapter](https://github.com/akpaevj/onec-debug-adapter) (MIT) — DAP + autoAttachTypes.
- [Admin guide: dbgs](https://kb.1ci.com/1C_Enterprise_Platform/Guides/Administrator_Guides/1C_Enterprise_8.3.23_Administrator_Guide/Appendix_4._Auxiliary_utilities/4.11._Debug_server__dbgs_/).
- [Standalone debug example](https://kb.1ci.com/1C_Enterprise_Platform/Guides/Administrator_Guides/1C_Enterprise_8.3.22_Administrator_Guide/Chapter_7._Standalone_server/7.4._Examples_of_managing_and_starting_the_standalone_server/7.4.8._Starting_the_standalone_server_in_debug_mode/) — argv клиента `/DEBUG -http -attach /DEBUGGERURL"…"`.

## 11. Воспроизведение

См. [README fixture](../../tests/fixtures/debug_spike/README.md).

Ожидание happy path (`--no-pause`): attach `registered` → `targetStarted` → STOP на CommonModule:5 или App:9 → eval `correctly` → Continue → detach `1`.

## Выводы для ADR-031 (чек-лист)

- [x] Discovery/argv `dbgs` (Linux live; Windows — docs).
- [x] Клиент: `/Debug -http -attach` + DebuggerURL; plain `/Debug` недостаточен.
- [x] Порт: не хардкодить 1550; notify UTF-16.
- [x] Cmd’ы, namespaces, ping без тела, autoAttach, BP с propertyID.
- [x] Eval sync в POST (на 8.3.25); стек — брать leaf frame.
- [x] `force_detach` / `ibInDebug` recovery.
- [x] DISPLAY только клиенту.
- [x] Fixture + прототип для последующих unit/E2E (#138+).
- [ ] Product: расширить `runtime.start --debug` / schema `debug` — в #136–#140.
