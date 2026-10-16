# Fixture: HTTP Debug Protocol spike (#135)

Минимальный XML-проект для [spike #135](../../../docs/spikes/135-http-debug-protocol.md):
конфигурация `DebugSpike` + общий модуль `ОтладкаДемо` с предсказуемой строкой точки останова.

| Поле | Значение |
|------|----------|
| Модуль | `CommonModule.ОтладкаДемо` |
| objectID | `b7e2c4a1-8f3d-4a6e-9c1b-2d5e8f0a3b6c` |
| propertyID (тело CommonModule) | `d5963243-262e-4398-b4d7-fb16d06484f6` |
| Строка BP CommonModule | **8** (`Проверка = Сообщение; // BP-LINE`) — после всех присвоений |
| ApplicationModule objectID | `d4e5f6a7-b8c9-4d0e-1f2a-3b4c5d6e7f80` (Configuration uuid) |
| ApplicationModule propertyID | `d22e852a-cf8a-4f77-8ccb-3548e7792bea` |
| Триггер | `ВыполнитьДемо` → `ЗавершитьРаботуСистемы(Ложь)` |
| BP ApplicationModule | строка **4** (`ОтладкаДемо.ВыполнитьДемо…`) — `ИмяСценария` уже задан |
| Linux / IDE | толстый клиент на **том же DISPLAY**, что IDE: на BP может «заморозить» весь GUI — смотри milestone / запускай CLI во внешнем терминале |
| Alias file IB | `DefAlias` |

## Серверные модули (M6, #140)

Кроме клиентского `ManagedApplicationModule` и `ОтладкаДемо`, в фикстуре есть серверный код
(файловая ИБ + толстый клиент: клиент и сервер — одна цель отладки, в стеке видны оба слоя).

| Модуль | Файл | BP | Что проверяем |
|--------|------|----|---------------|
| ManagedApplicationModule (клиент) | `src/main/Ext/ManagedApplicationModule.bsl` | **4** | старт, переменные, `step-over` на строку 5 |
| Справочник `Товары`, модуль менеджера | `src/main/Catalogs/Товары/Ext/ManagerModule.bsl` | **3** | серверный модуль менеджера |
| Справочник `Товары`, модуль объекта | `src/main/Catalogs/Товары/Ext/ObjectModule.bsl` | **4** | `ПередЗаписью`, реквизиты объекта |
| `CommonModule.ОтладкаСервер` (Server, ServerCall) | `src/main/CommonModules/ОтладкаСервер/Ext/Module.bsl` | **10** | серверный общий модуль, `СерверныйРезультат` = 21/42 |

Автотест (основная конфигурация, клиент + сервер): `tests/test_m6_acceptance.py` (маркер `integration`; нужны платформа 1С, `dbgs`, `DISPLAY`) —
`runtime start --debug` с 4 BP → `debug wait` → переменные/`eval` → `step-over` → `continue` ×3 → `runtime stop`;
шаги через CLI — `test_m6_acceptance_steps_cli` (`step-over` / `step-in` / `step-out` от BP `ManagedApplicationModule:4`)
(проверяет, что `session.json`, `ping.pid`, `server.pid` удалены).

## Расширение `DebugExt` (M6, `src/cfe/debug_ext`)

`configurations[main].extensions[debug_ext]` (name `DebugExt`, prefix `Расш_`); `build` грузит его
в ту же файловую ИБ (`import:DebugExt`, `apply:DebugExt`).

| Модуль | Файл | BP | Что проверяем |
|--------|------|----|---------------|
| `CommonModule.ОтладкаДемо` (адоптированный, клиент) | `src/cfe/debug_ext/CommonModules/ОтладкаДемо/Ext/Module.bsl` | **5** | перехватчик `&После("ВыполнитьДемо")`, `РасширениеСценарий` |
| `CommonModule.Расш_ОтладкаСервер` (Server, ServerCall) | `src/cfe/debug_ext/CommonModules/Расш_ОтладкаСервер/Ext/Module.bsl` | **7** | серверный модуль расширения, `РасширениеРезультат` = 42 |

Порядок остановок при `--bp` на оба модуля: ManagedApplicationModule → `ОтладкаДемо` (ext) →
`Расш_ОтладкаСервер` (ext). Адоптированный модуль имеет **свой** uuid (`ExtendedConfigurationObject`
указывает на основной `b7e2c4a1-…`); BP ставится по uuid расширения с типом `ExtensionModule`.

```bash
1c-dev runtime start --debug \
  --bp src/cfe/debug_ext/CommonModules/ОтладкаДемо/Ext/Module.bsl:5 \
  --bp src/cfe/debug_ext/CommonModules/Расш_ОтладкаСервер/Ext/Module.bsl:7
1c-dev debug wait && 1c-dev debug variables && 1c-dev debug continue
1c-dev runtime stop
```

Автотест расширения: `test_m6_acceptance_extension_cli` (весь сценарий через `CliRunner`,
`runtime start --bp` → `debug wait`/`variables`/`eval`/`continue` → `runtime stop`).

Для ручного `runtime start --debug` в `project.yaml` нужен `debug.port`.

```bash
cp -r tests/fixtures/debug_spike /tmp/debug-spike && cd /tmp/debug-spike
1c-dev build
# 1550/1540/1541/1560 на этой машине заняты кластером 1С — не брать вслепую
ss -tln | grep -E ':(1540|1541|1550|1560)\s' || true
python3 run_http_debug.py --ib .1c-dev/runtime/main --port 2550 --no-pause
# только CommonModule BP:
python3 run_http_debug.py --ib .1c-dev/runtime/main --port 2550 --no-pause --common-module-only --eval-expr 'Значение'
```

`run_http_debug.py` — прототип (не продукт). Клиенту нужен `DISPLAY` (на spike: `:0`).
`dbgs` пишет `--notify` в **UTF-16 LE**.

Вход для ADR: [135-http-debug-protocol.md](../../../docs/spikes/135-http-debug-protocol.md) → **ADR-031** (#136; не ADR-030 — уже занят).
