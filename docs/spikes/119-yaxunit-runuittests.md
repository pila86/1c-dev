# Spike #119: YaXUnit `RunUnitTests` + jUnit (fixture, формат отчёта)

**Дата:** 2026-10-03  
**Платформа:** 8.3.25.1560 (Linux x86_64, `/opt/1cv8/x86_64/8.3.25.1560/`)  
**YaXUnit:** 25.12 (`YAxUnit-25.12.cfe`, [релиз](https://github.com/bia-technologies/yaxunit/releases))  
**Issue:** [#119](https://github.com/pila86/1c-dev/issues/119)  
**Граница:** механика запуска и формат отчёта. Контракт Test API — [ADR-029 (#120)](https://github.com/pila86/1c-dev/issues/120), manifest — [#121](https://github.com/pila86/1c-dev/issues/121). Продуктового кода нет.

Fixture: [tests/fixtures/yaxunit_spike/](../../tests/fixtures/yaxunit_spike/README.md) (две test-extension + `run_yaxunit.py` — прототип запуска и разбора jUnit).

## TL;DR для ADR-029

| Вопрос | Ответ |
|--------|-------|
| Вызов | `1cv8 ENTERPRISE /F<ib> /DisableStartupDialogs /DisableStartupMessages /DisableSplash /L ru /Out <out.log> "/CRunUnitTests=<abs cfg.json>"` |
| Нужен X-сервер | Да. Без `DISPLAY` — exit 255, ничего не пишет. В headless — `xvfb-run -a` |
| Конфиг | JSON-файл; фильтры только через него (CLI-override — только плоские скаляры) |
| Отчёт | jUnit XML (`reportFormat: "jUnit"`). `JSON` в 25.12 **не поддерживается**; `allure` — каталог `*-result.json` |
| Exit code процесса | **Всегда 0** при падении тестов. Результат — в отчёте и/или в файле `exitCode` |
| Discover | Режима «только список» **нет** (см. ниже) |
| Extension → suite | `testsuite@package` = имя extension → маппинг на `tests[].extensions` прямой |
| Default без фильтров | Грузятся **все** extension со своими общими модулями → в продукте всегда задавать `filter.extensions` |

## 1. Окружение и подготовка ИБ

Build-часть — штатный `1c-dev build` (M4) без доработок: `create` → `import`/`apply` конфигурации → `import:<ext>`/`apply:<ext>` на каждое extension (порядок `extensions[]`).

YaXUnit в проект попадает как обычное extension `purpose: tests`:

```bash
1c-dev extension add --id yaxunit --name YAXUNIT --purpose tests --from YAxUnit-25.12.cfe
```

(`--from .cfe` выгружает ~10 МБ XML в `src/cfe/yaxunit`; в git fixture это **не** коммитим — Apache-2.0, размер, версия обновляется отдельно.)

**Имя extension YaXUnit — `YAXUNIT`** (не `YAxUnit`): так оно зашито в `.cfe`; `filter.extensions` сравнивается без учёта регистра.

### Обязательно перед запуском: safe-mode

Платформа создаёт extension с `safe-mode=yes`, `unsafe-action-protection=yes`. Тесты YaXUnit так не работают (в эксперименте с оставшимся `safe-mode` клиент завис до timeout). `build` этого не делает, нужен отдельный шаг для **каждого** extension с `purpose: tests` и самого YAXUNIT:

```text
ibcmd extension update --db-path=<abs ib> --data=<abs data> --name=<Name> --safe-mode=no --unsafe-action-protection=no
```

- Пути в ibcmd — только **абсолютные**: с относительным `--data` получил «Рабочий каталог заблокирован процессом: 0».
- Шаг идемпотентен и не требует `apply`; значения видны в `ibcmd extension list` и в `properties` отчёта (`Расширения`: `БезопасныйРежим`, `ЗащитаОтОпасныхДействий`).

## 2. Вызов `RunUnitTests`

```text
1cv8 ENTERPRISE /F<abs ib>
  /DisableStartupDialogs /DisableStartupMessages /DisableSplash
  /L ru /Out <out.log>
  "/CRunUnitTests=<abs cfg.json>[;key=value;...]"
```

- Время прогона на fixture (7 тестов): **1.0–1.5 с** end-to-end, включая старт 1cv8.
- `/Out` в норме пустой; сюда попадают только «Невосстановимая ошибка…» и «Зацикливание обработки глобальной ошибки…».
- Параметр без значения (`RunUnitTests`) = интерактивный режим (`showReport=true`, `closeAfterTests=false`) — для продукта не годится.
- CLI-override (с 25.09) `;key=value` работает **только для плоских ключей** (`reportPath`, `exitCode`, `closeAfterTests`, …) — проверено (`;reportPath=…;exitCode=…`); вложенный `filter` через CLI не задаётся. Значения `true/false/число` приводятся к типам. Приоритет у CLI.
- Дисплей: `DISPLAY=:0` — работает напрямую; без `DISPLAY` — exit 255 мгновенно; с `xvfb-run -a` — работает (запас для CI/агента).

### Конфиг (минимум и рекомендуемый для продукта)

Для продукта: `reportPath` + `closeAfterTests: true` (при `false` отчёт пишется, но процесс не завершается; поведение при отсутствии ключа не проверялось — задавать явно).

```json
{
  "filter": { "extensions": ["Tests1"] },
  "reportFormat": "jUnit",
  "reportPath": "/abs/out/junit.xml",
  "exitCode": "/abs/out/exit-code.txt",
  "closeAfterTests": true,
  "showReport": false,
  "logging": { "file": "/abs/out/yaxunit.log", "console": false, "level": "debug" }
}
```

| Поле | Наблюдение |
|------|-----------|
| `closeAfterTests` | Должно быть `true`. При `false` — процесс висит бессрочно (после записи отчёта) |
| `reportPath` | Файл для jUnit. Каталог создаётся автоматически. Относительный путь требует `workspacePath` (иначе не используем — только абсолютные) |
| `reportFormat` | `jUnit` и `allure` работают; `JSON`/`json` → `[ERR] Отчет в формате … не поддерживается`, файл не пишется, rc=0 |
| `reports[]` | Массив `{format, path}` в 25.12 в наших экспериментах **не создал файлов** (jUnit тоже). Использовать `reportFormat`+`reportPath` |
| `exitCode` | **Путь к файлу**, в который пишется `0` (успех) / `1` (есть failed/error), UTF-8 **с BOM**. Код возврата процесса не меняется |
| `logging.file` | Нужен: ошибки загрузки модулей (компиляция BSL) видны только здесь. `level: debug` показывает «Анализ модуля», «Запуск тестов модуля `<Ext>.<Модуль>`» |
| `filter.*` | См. раздел 5 |

## 3. Формат jUnit-отчёта

Корень `<testsuites>` с `<properties>` (окружение прогона) и набором `<testsuite>`. **Один `testsuite` = (тестовый набор YaXUnit × контекст вызова) в одном модуле.**

```xml
<testsuites>
  <properties>
    <property name="ВерсияПлатформы" value="8.3.25.1560"/>
    <property name="ТестовыйДвижок" value="YAXUNIT"/>
    <property name="ВерсияТестовогоДвижка" value="25.12"/>
    <property name="Расширения" value="|YAXUNIT |25.12 |Нет |Нет | …"/>   <!-- имя | версия | безоп.режим | защита -->
    <!-- … ОС клиента/сервера, ФайловаяБаза, ВремяЗапуска и т.д. -->
  </properties>
  <testsuite id="0" name="Арифметика [Сервер]" classname="ОМ_Арифметика" package="Tests1"
             context="Сервер" tests="4" failures="1" errors="1" skipped="1"
             time="0.044" timestamp="2026-10-03T09:03:35">
    <properties><property name="context" value="Сервер"/></properties>
    <testcase name="Сложение" classname="ОМ_Арифметика.Сложение" time="0.004" context="Сервер"/>
    <testcase name="Деление" classname="ОМ_Арифметика.Деление" time="0.009" context="Сервер">
      <failure message="Ожидали, что проверяемое значение `2,5` равно `3`, но это не так." type="Утверждений">…стек + &lt;expected&gt;/&lt;actual&gt;…</failure>
    </testcase>
    <testcase name="ДелениеНаНоль" …><error message="Исполнения: Деление на 0" type="Исполнения">…стек…</error></testcase>
    <testcase name="Пропущенный" …><skipped message="Пропуск для spike" type="Пропущен"/></testcase>
  </testsuite>
</testsuites>
```

### Маппинг в structured JSON (вход для PRD §26 / ADR-029)

| jUnit | Test Result JSON |
|-------|------------------|
| `testsuite@package` | `extension` (имя; по нему маппится suite манифеста) |
| `testsuite@classname` | `module` |
| `testsuite@name` (`<Набор> [<Контекст>]`) | `testSet` (+ `context` из `@context`) |
| `testcase@name` | `test` (полный id для `runOne`: `<Module>.<Method>[.<Context>]`) |
| `testcase@time`, `testsuite@time` | `durationSec` |
| нет child | `status: passed` |
| `<failure>` | `status: failed`, `message` = атрибут, `details` = текст (`expected`/`actual` внутри) |
| `<error>` | `status: error` (исключение в тесте / вне проверок), `message`, `details` |
| `<skipped>` | `status: skipped`, `message` |
| `testsuite@tests/failures/errors/skipped` | агрегаты (проверить сверкой с testcase) |

Заметки:

- `failure` — нарушение утверждения (`ЮТест.ОжидаетЧто`), `error` — исключение; для `exit 5` (`TEST_FAILURE`) считать **оба**.
- Текст `failure/error` — десятки строк стека YaXUnit (~30), для JSON-ответа агенту нужен `message` + усечённый `details` (лимит / `--verbose`).
- Один и тот же тест в нескольких контекстах (`Сервер`, `КлиентУправляемоеПриложение`) → несколько `testsuite`/`testcase` с одним `name`; идентификатор должен включать `context`. Проверено только `Сервер` (тесты вызываются на сервере без `&НаКлиенте`-контекста).
- Если фильтр ничего не выбрал — отчёт **валиден**, `<testsuites>` с одними `properties`, rc=0, `exitCode`-файл `0`: «0 тестов» ≠ ошибка запуска. Продукт должен явно сообщать `total == 0`.

## 4. Exit code и ошибки запуска

| Ситуация | Процесс | Отчёт | Файл `exitCode` | Что делает продукт |
|----------|---------|-------|-----------------|--------------------|
| Все тесты прошли | 0 | есть | `0` | ok |
| Есть failed/error | **0** | есть | `1` | `TEST_FAILURE` (5) по отчёту/файлу |
| Фильтр без совпадений | 0 | пустой | `0` | `total=0` — warn/error по решению ADR |
| Ошибка компиляции модуля теста | 1 | **нет** | нет | `RUNTIME_FAILURE`/init-error; детали в `yaxunit.log` (`[ERR] ЗагрузкаТестов …`), `/Out`: «Невосстановимая ошибка» |
| Неверный путь в `filter.tests` (нет `.`, >3 частей) | не завершается | нет | нет | **hang**: бесконечный цикл ошибок загрузки, в логе тысячи `[ERR]`, `/Out`: «Зацикливание обработки глобальной ошибки…». Валидировать путь `Module.Method[.Context]` до запуска |
| `closeAfterTests=false` | не завершается | есть | есть | всегда `true` |
| Нет `DISPLAY` | 255 | нет | нет | `ENV_UNAVAILABLE`; fallback `xvfb-run` |
| `safe-mode=yes` у extension | наблюдался timeout | нет | нет | предпроверка + `extension update` до запуска |
| Несуществующее extension/модуль/метод в фильтре | 0 | пустой (метод: модуль загружен, тестов нет) | `0` | как «0 тестов» |

**Требования к adapter:** обязательный timeout; при timeout убивать **группу процессов** (`start_new_session` / `killpg`: `xvfb-run` + `Xvfb` + `1cv8`); оставшиеся после `subprocess.run(timeout=…)` `1cv8` продолжают висеть (проверено). Различать «отчёт есть» (результат) и «отчёта нет» (ошибка запуска), опираясь на jUnit, а не на rc.

## 5. Фильтры, suites и extensions

Поля `filter` (см. `ЮТФильтрацияСлужебный.УстановитьКонтекст`; все проверены на fixture):

| Ключ | Тип | Поведение (проверено) |
|------|-----|-----------------------|
| `extensions` | `[Name]` | Только модули этих extension; **без учёта регистра**. `["Tests2"]` → 1 модуль; `["Nope"]` → 0 тестов |
| `modules` | `[Module]` | Только эти общие модули (`["ОМ_Арифметика"]`) |
| `suites` | `[Набор]` | Имя тестового набора YaXUnit (`Логика`); модули всё равно загружаются (`3 сценариев`), отчёт содержит только подходящие наборы |
| `tests` | `["Module.Method[.Context]"]` | Точные тесты; `["ОМ_Арифметика.Сложение","ОМ_Строки.Длина"]` → по тесту в каждом из двух extension. Суженный список модулей выводится из `tests` |
| `tags` | `[Tag]` | Тег не найден → пустой отчёт |
| `contexts` | `[Context]` | Не используется в spike (только `Сервер`) |

**Терминология:** «suite» в манифесте 1c-dev (`tests[]`, набор extension) ≠ «suite/набор» YaXUnit (`ДобавитьТестовыйНабор`). В ADR-029 назвать явно: manifest suite = `testSuite`, YaXUnit set = `testSet`/`group`.

### Default без фильтров (закрытие TBD M5)

Без `filter.extensions` YaXUnit перебирает **все общие модули всех extension** (кроме подсистемы `ЮТДвижок`) и у каждого вызывает `ИсполняемыеСценарии()` — в логе: «Анализ модуля: …», для нетестовых — «Пропущен, это не тестовый модуль». Это означает: (а) побочные вызовы в модулях product-extension, (б) в прогон попадут тесты **любых** extension, не только из выбранного suite.

**Рекомендация для ADR-029 / #123:**

1. `test.run` без фильтров = запуск **всех** suites выбранной `--config`: `filter.extensions = ⋃ tests[].extensions` (имена из `extensions[].name`, **без** `YAXUNIT`). Никогда не оставлять `filter.extensions` пустым.
2. `--suite <id>` → `filter.extensions = tests[id].extensions`.
3. Фильтр модуля / теста (`--module`, `runOne <Module.Method>`) → `filter.modules` / `filter.tests` **вместе с** `filter.extensions` своего suite. `filter.tests`/`modules` адресуют модуль по имени без extension; уникальность имён общих модулей между extension в одной ИБ в spike **не проверялась** — при неоднозначности требовать `--suite`.
4. Один запуск 1cv8 на `test.run` (выбранные suites объединяются в один `filter.extensions`) — старт ~1 с, но это один процесс на ИБ; параллельные прогоны на одной file IB не поддерживать (блокировки не проверялись).
5. Имя runner-extension (`YAXUNIT`) брать из `extensions[]` с `purpose: tests`, не входящих ни в один `tests[].extensions` (или явное поле) — решить в ADR.

## 6. Discover / list

В YaXUnit 25.12 **нет** режима «загрузить сценарии и вывести список без выполнения»:

- `filter.tags`/`filter.suites` на несуществующее значение загружают сценарии (`Загрузка сценариев завершена. N сценариев`), но в отчёт и лог имена **тестов** не попадают (логируются только модули).
- `reportFormat` не умеет «dry run».

Варианты для `test.discover` / `test.list` (решение — ADR-029):

| Вариант | Плюсы | Минусы |
|---------|-------|--------|
| A. **Статический** разбор source (extension с `purpose: tests` из манифеста → общие модули с экспортной `ИсполняемыеСценарии`) | Без платформы и ИБ; быстро; детерминированно на уровне **модулей** | Список тестов в цепочке `ЮТТесты.ДобавитьТестовыйНабор(...).ДобавитьТест(...)` парсится хрупко (динамика, циклы, тесты не в `ИсполняемыеСценарии`) |
| B. **Полный прогон** как инвентаризация | Точный список тестов | Выполняет тесты (побочные эффекты, время); не «list» |
| C. Рекомендуемый для v1: `discover` = A на уровне **модулей/extension/suites** (манифест + source), `list` тестов = из **последнего отчёта** (`report`) либо A best-effort; точный список тестов даёт только `run` | Честный контракт, без платформы | `list` на чистом проекте — неполный |

## 7. Что не покрыто / риски

- Проверена одна версия платформы (8.3.25.1560) и YaXUnit (25.12); 8.3.23.1739 и 25.04 не прогонялись. Схема `/C"RunUnitTests=…"` и overrides `;key=value` требуют YaXUnit ≥ 25.09 (override), базовый `=<json>` — старее.
- Windows не проверялся (пути, кавычки `/C"…"`).
- Клиентские контексты (`КлиентУправляемоеПриложение`, `ВызовСервера`) и тонкий клиент (`1cv8c`) не проверялись; прогон шёл в толстом клиенте (`1cv8 ENTERPRISE`).
- Параллельные запуски / блокировка file IB не проверялись.
- `reports[]` (multi-report) — не заработал, причина не установлена (возможно, требует иных ключей; в доке 25.12 ключи `format`/`path`).
- Большие отчёты (>1000 тестов) и производительность — не мерились.

## 8. Находки по текущему продукту (до M5)

1. **Баг шаблона extension scaffold (блокер M5-accept):** [templates/extension/src/cfe/_ext/Languages/Русский.xml.tmpl](../../templates/extension/src/cfe/_ext/Languages/Русский.xml.tmpl) пишет `<ExtendedConfigurationObject>` = собственный `uuid` языка extension, а должен быть `uuid` языка **расширяемой конфигурации** (в spike — `b3bc575b-…` из `src/main/Languages/Русский.xml`). Следствие: `ibcmd config import/apply/check` проходят «успешно», но extension не применяется в сессии — модули/обработчики extension невидимы клиенту (YaXUnit: «0 сценариев»). Designer ловит это явно (`/UpdateDBCfg -Extension …` → «Значение контролируемого свойства ОбъектРасширяемойКонфигурации у объекта Язык.Русский не совпадает…»). Нужен отдельный issue (M4 follow-up); в fixture значение исправлено вручную.
2. **`extension add --id test-ext1`** нормализует id в `test_ext1` (дефис → `_`; каталог `src/cfe/test_ext1`); эскиз манифеста в [m5-tests.md](../milestones/m5-tests.md) использует `test-ext1` — выровнять.
3. **Safe-mode** extension не отключается ни `build`, ни scaffold — см. раздел 1. Для M5: шаг подготовки (`build` для `purpose: tests` или pre-flight `test.*` через `ibcmd extension info/update`).
4. `build` пересоздаёт extension только через `import`/`apply` (без `extension create`): purpose получается `add-on`; для YaXUnit этого достаточно.
5. Имя процедуры теста не должно совпадать с ключевым словом BSL (`Истина`) — иначе ошибка компиляции модуля → «Невосстановимая ошибка» (rc=1, нет отчёта).

## 9. METR как референс (без product-пути)

[alkoleft/mcp-onec-test-runner](https://github.com/alkoleft/mcp-onec-test-runner) (commit `b765b35`, GPL-3.0): `YaXUnitRunner` пишет временный JSON-конфиг (`reportPath`, `logging.file`, `filter`, …) и запускает ENTERPRISE с `RunUnitTests=<abs json>`; результат берёт из отчёта, а не из rc (в логе только `result.exitCode`). Совпадает с нашей механикой; подтверждает решение **не** брать METR в product-путь (ADR-029): GPL, MCP-only, пересечение с `build`/`check`/`runtime`.

## 10. Воспроизведение

См. [README fixture](../../tests/fixtures/yaxunit_spike/README.md): копия fixture → `extension add --from YAxUnit-25.12.cfe` → `build` → `ibcmd extension update …` → `run_yaxunit.py`. Ожидаемый результат на полном прогоне: 7 тестов (4 passed, 1 failed, 1 error, 1 skipped), `exitCode`-файл `1`; `--filter '{"extensions":["Tests2"]}'` → 2 passed, `exitCode` `0`.

## Выводы для ADR-029 (чек-лист)

- [x] Вызов и конфиг: `/CRunUnitTests=<abs json>`, `closeAfterTests=true`, jUnit, `exitCode` как файл, `logging.file`.
- [x] Структурный отчёт: jUnit → JSON (маппинг §3); `package`=extension.
- [x] Default multi-suite: все suites, `filter.extensions` всегда явный (§5).
- [x] Фильтры: `extensions`/`modules`/`suites`/`tests`/`tags` работают; `runOne` = `filter.tests` (`Module.Method[.Context]`).
- [x] Discover: нативного режима нет → вариант C (§6).
- [ ] Schema version: рекомендация — **additive** `configurations[].tests` внутри schema `"2"` (необязательная секция; не требует новой структуры верхнего уровня и не ломает проекты M4); bump — только если в ADR/#121 появятся несовместимые изменения. Финальное решение — ADR-029.
- [x] Pre-flight: X-сервер/`xvfb-run`, safe-mode, YAXUNIT в ИБ, timeout + kill process group.
