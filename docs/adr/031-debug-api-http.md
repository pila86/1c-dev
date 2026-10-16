# ADR-031: Debug API (CLI/MCP over HTTP Debug Protocol)

**Статус:** Accepted  
**Дата:** 2026-10-13

## Контекст

M6 ([m6-debug.md](../milestones/m6-debug.md)) требует единый Debug API (CLI + MCP): агент и CI
подключаются к HTTP-серверу отладки 1С (`dbgs`), ставят точки, ждут остановку, читают
стек/переменные, вычисляют выражения и шагают — без Конфигуратора и без shell.

Spike [#135](https://github.com/pila86/1c-dev/issues/135)
([docs/spikes/135-http-debug-protocol.md](../spikes/135-http-debug-protocol.md)) зафиксировал:

- discovery/argv `dbgs`, HTTP `POST /e1crdbg/rdbg?cmd=…`, ping без тела, autoAttach, BP/eval;
- клиент только с `/Debug` **не** регистрируется на HTTP `dbgs` — нужны `/Debug -http -attach`
  и `/DebuggerURL`;
- ping loop in-process ~500 ms достаточен; `force_detach` / `ibInDebug` recovery;
- порт **не** хардкодить как 1550 (часто занят кластером).

Закладка [ADR-019](019-runtime-client-lifecycle.md): `--debug` → `/Debug`; tools `debug.*` — M6.
Номер **031** (не 030 — занят Designer `/CheckModules`, ADR-030).

Нужно заморозить границу (HTTP vs DAP vs внешние MCP), контракт операций, state, schema,
exit codes и связь с `runtime.start --debug` — без реализации adapter/CLI/MCP в этом ADR.

## Решение

### 1. Свой Debug API facade поверх прямого HTTP (не DAP-first, не vendor MCP)

| Поверхность | Контракт |
|-------------|----------|
| CLI | `1c-dev debug …` (подкоманды, стиль `test` / `runtime`) |
| Core | `core/debug/` — оркестрация, `DebugResult.to_payload()`, diagnostics `1CD…` |
| Adapter | `adapters/debug_http/` — XML/HTTP к `dbgs`, ping/events, session |
| MCP | `debug.*` в `1c-dev mcp` (thin wrapper над `core.debug`, ADR-010) |

```text
Agent / CLI  ──►  core.debug.*  ──►  adapters/debug_http  ──►  dbgs (HTTP)
IDE (человек) ──►  DAP (внешний adapter)  ──►  dbgs (HTTP)
                      ▲
                      └── ide configure → launch.json (should, #143)
```

| Граница | Решение |
|---------|---------|
| Backend для агента/CLI | **Прямой HTTP Debug Protocol** → `dbgs` |
| DAP | Только для **IDE** (человек). Не основной путь агента. Reuse [onec-debug-adapter](https://github.com/akpaevj/onec-debug-adapter) / [bsl-debug-server](https://github.com/yukon39/bsl-debug-server) — не fork в core |
| [1c-debug-mcp](https://github.com/liga-1c-command/1c-debug-mcp) | MIT-референс механики (XML, ping, autoAttach); **не** vendor, не companion MCP |
| Platform Tools MCP | Только референс сценариев; IDE-IPC — не product-путь |
| Свой debugger / свой DAP-server | **Нет** (PRD §4 non-goal) |

Продукт — orchestration layer: один контракт CLI+MCP, без `shell.exec`, без парсинга stdout CLI.

### 2. Манифест: top-level optional `debug` (schema `"2"`)

**Принято:** один top-level блок `debug` в `.1c-dev/project.yaml`.  
**Отвергнуто:** поля `debug.*` внутри `runtimes[]` (и дублирование в двух местах).

Обоснование: один `dbgs` на scope; URL/порт/alias — свойства debug-сервера, не ИБ.
Выбор ИБ/клиента — через `--config` / `--runtime` (как test/build, ADR-026). Paths CF/CFE
берутся из `configurations[].source` / `extensions[].source`, не дублируются в `debug`.

```yaml
# schema "2" additive — блок необязателен
debug:
  host: localhost          # default: localhost
  port: 2550               # обязателен при старте dbgs нами; default 1550 НЕ задаём
  infobaseAlias: DefAlias  # file IB: DefAlias (неизменяемый)
  autoAttachTypes: [Client, ManagedClient, Server, ServerEmulation]
  # password в манифесте запрещён (schema); только env ONEC_DEBUG_PASSWORD — см. §2a
```

| Поле | Обязательно | Смысл |
|------|-------------|--------|
| `host` | нет | Host `dbgs` / DebuggerURL; default `localhost` |
| `port` | нет в schema; **нужен** при `debug.server.start` | Порт слушает `dbgs`. Нет «тихого» default 1550 — CLI/manifest/portRange |
| `infobaseAlias` | нет | Alias на debug-сервере; default `DefAlias` для file IB |
| `autoAttachTypes` | нет | Типы auto-attach (канон платформы / onec-debug-adapter) |

Bump major schema **не** нужен (только optional). Валидация полей — [#137](https://github.com/pila86/1c-dev/issues/137).

### 2a. Пароль dbgs

- Пароль задаётся **только** через env `ONEC_DEBUG_PASSWORD`; `debug.password` в манифесте
  schema отвергает (секрет не попадает в git). Явный аргумент функции `password=...`
  (в т.ч. пустая строка) важнее env.
- Единая точка чтения — `core.debug.common.resolve_debug_password`; используется в
  `debug server start` (`dbgs --password=…`) и `debug attach` (`<credentials>` в `attachDebugUI`).
- Пароль **не** пишется в `session.json`, `server.meta.json`, payload результата и логи;
  в сообщениях ошибок запуска `dbgs` маскируется (`mask_secret` → `***`).
- Известное ограничение платформы: `dbgs` принимает пароль только аргументом
  `--password=…`, поэтому он виден в `ps` локальным пользователям той же машины.
  Для локальной отладки file IB пароль обычно не нужен.

### 3. Операции API (must)

Один контракт; CLI — **подкоманды** (как `runtime start`, `test run`); MCP — имена с точками.

| Операция | CLI | MCP | Core |
|----------|-----|-----|------|
| dbgs lifecycle | `debug server start\|stop\|status` | `debug.server.start` / `.stop` / `.status` | `server_*` |
| Сессия | `debug attach` / `detach` / `force-detach` | `debug.attach` / `debug.detach` / `debug.forceDetach` | session |
| Цели | `debug targets` | `debug.targets` | list + metadata ready |
| Breakpoints | `debug breakpoint set\|clear` | `debug.breakpoint` / `debug.clearBreakpoints` | moduleName / `--file` / ids |
| Ожидание | `debug wait [--timeout] [--fresh]` | `debug.wait` | wait_for_stop |
| Управление | `debug continue` / `step-over` / `step-out` / `pause` (+ `step-in` ⚠) | `debug.continue` / `debug.stepOver` / `debug.stepOut` / `debug.pause` | step + wait next stop (CLI `--no-wait` opt-out); over = platform `Step`; **`step-in` — known broken** |
| Инспекция | `debug stack` / `variables` / `eval <expr>` | `debug.stack` / `debug.variables` / `debug.evaluate` | last stop / targetId |
| Состояние | `debug status` | `debug.status` | session + targets + last stop |
| Index | `debug reload-metadata` | `debug.reloadMetadata` | rebuild UUID↔module cache |

**PRD §28** (`debug.start` / `debug.stop`) — convenience-обёртки (не отдельные must-tools):

| PRD | Семантика |
|-----|-----------|
| `debug.start` | ensure `debug.server` + `attach` (+ optional `runtime.start --debug` по явному флагу) |
| `debug.stop` | `detach` (+ optional `debug.server stop` по флагу) |

Silent auto-`runtime.start` внутри каждого `debug.*` — **запрещён**.

**Defaults:**

- `debug.wait` timeout: **30 s** (CLI/MCP override; без hang навечно).
- `--config` / `--runtime` — как test/build; default = default runtime выбранной config.
- Payload: structured JSON (`status`, `diagnostics[]`, `duration`, поля результата).
- Timeout wait без stop → `status: failed` + `1CD005`.

**Should (не blockers acceptance):** `raw_request` (opt-in, default off в MCP
descriptions); `ide configure` → launch.json; doctor soft `debug.http`.

**Не must:** EPF breakpoints (ограничение протокола 1С) — документировать `pause` + step.

### 4. State layout (под `.1c-dev/`)

Project-scoped (не per-runtime) каталог debug-сервера и сессии UI:

```text
.1c-dev/
  runtime/<id>/
    client.pid
    client.meta.json          # уже есть; debug.enabled, + debuggerUrl (M6)
  debug/
    server.pid                # если dbgs стартовали мы
    server.meta.json          # host, port, notify path, startedAt (opt)
    session.json              # url, alias, sessionId, attachedAt
                              # + lastStop / attachedTargets / breakpoints / lastTargetId
                              #   (persist между short-lived CLI-вызовами)
    modules-cache.json        # UUID ↔ module (mtime invalidate; #139)
```

- Одна активная debug-сессия на процесс CLI/MCP; для CLI stop-state пишется в `session.json`,
  иначе `stack`/`variables`/`continue` после отдельного `wait` теряют `last_stop` (`1CD006`/`1CD007`).
- Client pid/meta остаются per-runtime (ADR-019 / ADR-026).
- Module index — под `.1c-dev/debug/` (не рядом с `src/`), чтобы не засорять source tree.

### 5. Ping: единственный читатель — демон

`pingDebugUIParams` — серверный **long-poll (~5 с)**; событие отдаётся **один раз** на
запрос (замеры: spike #135 §5a). Отсюда контракт (рефакторинг M6):

1. **Один читатель ping.** Клиентский timeout ping **> 5 с** (`PING_HTTP_TIMEOUT_SEC` = 12 с);
   таймаут запроса — не ошибка. Два читателя / короткий timeout / пауза между
   запросами теряют `targetStarted` / `callStackFormed`.
2. **Читатель — демон** (`python -m core.debug.ping_worker`, `.1c-dev/debug/ping.pid`).
   Он же единственный владелец attach: `attachDetachDbgTargets` один раз на target +
   `setBreakpoints` из `session.json`; новые targets ловит по `targetStarted` и
   периодическим `getDbgAllTargetStates`. **Force re-attach запрещён** (ломает
   stopped target).
3. **CLI/MCP-команды не пингуют** — читают `session.json` (запись под `flock`,
   атомарная замена). Демон пишет `lastStop`, `attachedTargets`, `lastTargetId`.
4. **Один способ остановить всё:** `runtime stop` → клиент → демон → `detachDebugUI`
   → `dbgs` (только если запустили мы, есть `server.pid`) → `.1c-dev/debug`.
   Идемпотентно; ошибки teardown — warning.

Демон автозапускается с `attach` / `runtime start --debug --bp`; вручную:
`1c-dev debug ping start|stop|status`.

**`debug wait` — по состоянию:** если `lastStop` уже записан — возвращает сразу;
`--fresh` сбрасывает его. Если клиент (pid из `runtime start`) завершился без
остановки — быстрый отказ `1CD016`. Иначе поллинг диска до `--timeout` (`1CD005`).
`continue` по умолчанию ждёт следующую остановку; если клиент завершился (программа
отработала) — результат `ok` с warning `1CD016`.

**Шаги:** `step-in` / `step-over` / `step-out` поддерживаются (live acceptance пройден:
`test_m6_acceptance_steps_cli`, основная конфигурация и расширение). Прежний сбой `1CD005`
был вызван коротким ping timeout и несколькими читателями `pingDebugUIParams`; после
перехода на единственного читателя (демон) он не воспроизводится. Если программа
завершается во время шага (например, `step-out` из верхнего кадра), результат — `ok`
с warning `1CD016` (как у `continue`). `step-out` возвращает на **строку вызова** в
вызывающем кадре; следующий `step-over` переходит к следующей строке.
**Experimental остаётся только `pause`** (`breakOnNextLine`): live acceptance не пройден,
результат содержит warning. Auto-arm callee BP удалён.

### 6. Связь с `runtime.start --debug`

Spike: argv только `/Debug` **недостаточен** для HTTP `dbgs` (targets пустой).

**M6 обязан расширить** `runtime.start --debug` / MCP `debug=true`:

```text
… ENTERPRISE /F<ib> /Debug -http -attach /DebuggerURL"http://<host>:<port>"
```

| Источник DebuggerURL | Порядок |
|----------------------|---------|
| Явный CLI/MCP override | 1 |
| Живой `debug.server` (state / status) | 2 |
| Манифест `debug.host` + `debug.port` | 3 |

**Упрощённый UX:** `runtime start --debug --bp path/to.bsl:line[,line…]` (повторяемый):

```text
ensure dbgs → attach (демон) → setBreakpoints
  → сброс stale lastStop/targets → spawn 1cv8 --debug
  → poll session.json: демон прикрепил target (+ BP) → вернуть управление
```

`runtime start` **не ждёт остановку** (флаги `--wait` / `--wait-timeout` удалены):
дальше `debug wait` → `debug variables|eval` → `debug continue` → `runtime stop`.
`--bp` без `--debug` — ошибка проекта.

`debug.attach` ожидает живой `dbgs` и клиент, зарегистрированный на нём. Meta
`debug.enabled` дополняется фактом HTTP-attach (например `debuggerUrl` в `client.meta.json`).

Discovery `dbgs`: sibling рядом с `1cv8`/`ibcmd` (паттерн ADR-005); Windows — `bin\dbgs.exe`
(docs; live E2E — follow-up CI).

### 7. force_detach / recovery

| Сценарий | Поведение |
|----------|-----------|
| `force-detach` / `debug.forceDetach` | `detachDebugUI` + очистить `session.json` / session id |
| Attach → `ibInDebug` | detach текущей/чужой UI + retry attach (до **5**, как spike AttachWithRetry) |
| Мёртвый ping / HTTP 400 после рестарта dbgs | detach → reattach → restore breakpoints (best-effort) |
| Мёртвый клиент | targets пропадают; detach UI всё равно выполняется |

### 8. Diagnostics и exit codes

Префикс **`1CD…`**. Новый exit code **не** вводить (без amendment ADR-003).

| Ситуация | Code | Exit (ADR-003) |
|----------|------|----------------|
| Нет / не найден `dbgs` | `1CD001` | `ENV_UNAVAILABLE` (3) |
| `dbgs` не отвечает / порт занят не тем | `1CD002` | `RUNTIME_FAILURE` (4) |
| Нет активной сессии | `1CD003` | `RUNTIME_FAILURE` (4) |
| Модуль / `objectID` не резолвится | `1CD004` | `PROJECT_ERROR` (2) если нет в source; иначе (4) |
| Timeout `wait` | `1CD005` | `RUNTIME_FAILURE` (4) |
| Target не в stopped | `1CD006` | `RUNTIME_FAILURE` (4) |
| Клиент без HTTP `/Debug` / нет targets | `1CD007` | `RUNTIME_FAILURE` (4) |
| Клиент завершился без остановки (`wait`) | `1CD016` | `RUNTIME_FAILURE` (4) |
| Project / manifest | reuse `1CR002` / project codes | `PROJECT_ERROR` (2) |

Сессия и окружение отладки → **4**; нет бинаря `dbgs` → **3**; ошибки проекта/манифеста → **2**.
MCP: те же `diagnostics[]` в JSON; exit codes CLI на MCP не маппятся (ADR-010).

`source` в diagnostics: `"debug"` для product; `"platform"` для discovery `dbgs`.

### 9. Adapter / module resolve (контракт, не реализация)

- `adapters/debug_http/`: HTTP client, XML builders/parsers (namespaces spike §4), ping,
  event queue, session. Attribution MIT 1c-debug-mcp при reuse идей; **своя** реализация.
- Resolve: `moduleName` + `moduleType` + optional `extensionName` → `objectID` (+ `propertyID`).
  Для расширений `extensionName` обязателен при неоднозначности.
- Модули расширений (live 8.3.25, фикстура `debug_spike`/`DebugExt`): в `setBreakpoints`
  `moduleBPInfo/id/type` = **`ExtensionModule`** (не `ConfigModule`) + `extensionName` +
  `objectID` собственного/адоптированного объекта расширения (uuid из XML расширения, не
  `ExtendedConfigurationObject`). С `ConfigModule` и любым `extensionName` точка молча
  не срабатывает. Кадры стека расширения приходят без имени расширения — `extensionName`
  добавляется обратным поиском по индексу (`stack[].extensionName`).
  Путь `src/cfe/<ext>/…/Module.bsl` резолвится в корень расширения, даже если такой же
  относительный путь есть в основной конфигурации.
- Также (#145): путь к `.bsl` (`Catalogs/X/Ext/ObjectModule.bsl` → uuid из `Catalogs/X.xml` +
  `propertyID` по виду модуля) и escape `--object-id`/`--property-id`. CLI: `--file` и
  `--module` взаимоисключающие. Index расширен ObjectModule/ManagerModule/FormModule/RecordSetModule.
- BP только на **исполняемых** строках; голый комментарий не ловит (spike).
- Стек: текущий кадр = **последний** (leaf) в `callStackFormed`.
- Eval на 8.3.25: результат либо в теле POST (~0.1 с), либо — если на `dbgs` припаркован ping-long-poll (всегда при демоне) — приходит событием `exprEvaluated` в ping (~5 с). Демон сохраняет такое тело в `.1c-dev/debug/eval/<expressionResultID>.xml`, `eval`/`variables` при пустом теле POST ждут этот файл (`EVAL_ASYNC_WAIT_SEC`).

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| HTTP facade + свой CLI/MCP | Один контракт; CI без второго MCP | Свой XML/HTTP клиент | **Принято** |
| Vendor / companion `1c-debug-mcp` | Меньше кода | Два оркестратора, два конфига | **Отвергнуто** |
| DAP-first для агента | Совпадает с IDE | Event-driven; нет удобного `wait` | **Отвергнуто** для агента |
| Platform Tools MCP как backend | Готовые сценарии | IDE-IPC; ломает P1/P2 | **Отвергнуто** |
| Top-level `debug` | Один dbgs на scope | — | **Принято** |
| `debug.*` в `runtimes[]` | Ближе к ИБ | Дубль URL; N портов без нужды | **Отвергнуто** |
| Default port 1550 | «Как в доках» | Конфликт с кластером | **Отвергнуто** |
| Ping helper-process | Изоляция | Лишний процесс для stdio MCP | **Отвергнуто** |
| Ping in-process ~500 ms | Проще; spike ok | Держит процесс MCP | **Принято** |
| Оставить `--debug` = только `/Debug` | Совместимость argv | Targets пустые на HTTP dbgs | **Отвергнуто** для M6 |
| Schema bump `"3"` под `debug` | Явная major | Ломает без нужды | **Отвергнуто** (additive `"2"`) |
| Новый exit code под debug | Семантика «отладка» | Amendment ADR-003 | **Отвергнуто** |

## Последствия

- Реализация по волнам M6: [#137](https://github.com/pila86/1c-dev/issues/137) schema;
  [#138](https://github.com/pila86/1c-dev/issues/138) adapter; [#139](https://github.com/pila86/1c-dev/issues/139)
  module index; [#140](https://github.com/pila86/1c-dev/issues/140) core+CLI;
  [#145](https://github.com/pila86/1c-dev/issues/145) `--file` / ObjectModule (wave 2.5);
  [#141](https://github.com/pila86/1c-dev/issues/141) MCP; [#142](https://github.com/pila86/1c-dev/issues/142)
  doctor/AGENTS; [#143](https://github.com/pila86/1c-dev/issues/143) launch.json (should);
  [#144](https://github.com/pila86/1c-dev/issues/144) acceptance.
- Расширить `runtime.start --debug` до HTTP attach + DebuggerURL (в волне core/runtime, #140).
- Добавить discovery `dbgs` в platform discovery.
- Windows live E2E `dbgs` — follow-up (spike: Linux live; Windows — docs).
- Закладка ADR-019: `debug.*` реализуется по этому ADR; argv `--debug` уточняется.

## Связанные решения

- ADR-003 (exit codes), ADR-005 (discovery), ADR-010 (MCP thin wrapper),
  ADR-019 (runtime `/Debug` → M6), ADR-022 (`.1c-dev/`), ADR-026 (`runtimes[]`),
  ADR-029 (стиль facade Test API), ADR-030 (номер занят CheckModules — не путать)
- Issue [#136](https://github.com/pila86/1c-dev/issues/136); depends on spike [#135](https://github.com/pila86/1c-dev/issues/135)
- [M6](../milestones/m6-debug.md), spike [135-http-debug-protocol.md](../spikes/135-http-debug-protocol.md)
- PRD §28 Debug API, §32 debug tools, §7.9 Debug Adapter
- Внешние (референс): [liga-1c-command/1c-debug-mcp](https://github.com/liga-1c-command/1c-debug-mcp) (MIT),
  [akpaevj/onec-debug-adapter](https://github.com/akpaevj/onec-debug-adapter) (MIT, DAP),
  [yukon39/bsl-debug-server](https://github.com/yukon39/bsl-debug-server)
