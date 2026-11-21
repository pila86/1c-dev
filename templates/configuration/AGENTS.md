<!-- BEGIN 1c-dev -->
# Правила 1c-dev

## Запреты
- Не читать и не править исходники инструмента `1c-dev` (репозиторий, пакет, внутренности CLI/MCP).
- Не править generated artifacts; уважать source format проекта.
- Не выгружать конфигурацию вручную через Конфигуратор.
- Не выдумывать API платформы, конструкции языка и синтаксис запросов — только lookup (bsl-ls / `docs.*`), см. ниже.

## Документация платформы
- Неизвестное имя / конструкция → lookup, не invent. Workspace bsl-ls: `list_workspace_folders`; нет корня — `register_workspace_folder` на корень IDE (не `src/cf`); вызовы с `fileType=BSL`.
- Порядок выбора: текст **запроса** → `docs.*` (язык запросов); **цикл / условие / попытка / объявление / директива / оператор выражения** → `docs.*` (не `global_member_search`); **метод / свойство / тип** → bsl-ls + при необходимости `docs.*`.
- API (глобал): запрос = короткое имя **или** EN **или** короткий префикс → `global_member_search` → из ответа только **2–3 имени** (не слепой top-1, не цитировать весь JSON) → один `global_member_info`. Пусто → сменить запрос (EN / другой префикс / docs), не invent.
- Обзор семейства API компактнее: `docs.search` с `Глобальный контекст.<префикс>` (или имя/EN) → `docs.get`. Не голый «Глобальный контекст» и не тематические заголовки / оглавление СП (TOC через docs недоступен).
- Конструкции / операции: `docs.search` с `Оператор цикла` / `Оператор Если` / `Оператор Попытка` или точное имя/EN → `docs.get` **головы** оператора (не хвосты «Часть конструкции…»). Не голое «Оператор»/«Операторы» (шум схемы запроса). Query-карточки (`Логические операторы` и т.п.) не подменять ими BSL.
- Члены типа: `type_info`. У примитивов методов может не быть — операции часто глобалы или операторы языка; выяснять lookup’ом.
- После правок BSL unknown в diagnostics → снова lookup.

## Порядок
- Предпочитать MCP `1c-dev` и `bsl-language-server`, не shell и не Конфигуратор.
- Если нужной операции нет в MCP/CLI или она не закрывает задачу — допустимо править исходники конфигурации/расширения напрямую (BSL, XML и т.п. в source.path). После этого — тот же цикл: diagnostics → build → check → test.
- Greenfield: `project.init` → `configuration.add` → `project.get` → metadata.* / build.
- `project.init` создаёт только home (пустые `configurations[]` / `runtimes[]`), не XML.
- Переключение XML↔EDT: MCP `source.convert` (`to=edt|xml`) / CLI `1c-dev source convert` — не shell и не Конфигуратор. После convert те же `metadata.*` / `build` / `check` (имена tools не меняются).
- После правок BSL: diagnostics (bsl-ls) → build → check → `test.*`. `check` — по file IB после `build`.
- Тесты: MCP `test.discover` / `test.list` / `test.run` / `test.runOne` / `test.wait` / `test.report` или CLI `1c-dev test` (не сторонний MCP runner).
- Перед завершением задачи — semantic diff.
- Воспроизводимые **runtime**-сбои (не вместо `test.*`): MCP `debug.*` / CLI `1c-dev debug` (не shell, не Конфигуратор, не сторонний debug MCP). Doctor soft gap `debug.http` (dbgs + порт).
- Debug-цикл (runtime): MCP `runtime.start(debug=true, breakpoints=…)` / CLI `runtime start --debug [--bp …]` (ensure dbgs + `debug.attach` + BP) → действие → `debug.wait` → `debug.variables` / `debug.evaluate` → fix → `debug.continue` → `runtime.stop`. Коротко: «сломалось на строке N → vars → fix». Stepwise (`debug.server.start` → `debug.attach` → `debug.breakpoint` → `runtime.start(debug=true)`) — advanced. После `runtime.stop` явный `debug.detach` часто даёт `1CD003` — нормально (teardown уже сделал).
- Debug упавшего теста: `test.run` / `test.runOne` с `debug=true` и `breakpoints` (CLI `--debug --bp`) → `status: running` → `debug.wait` (**`fresh=false`**, дефолт — стоп часто уже в `session.json`) → vars/eval/continue → `test.wait` (jUnit + teardown debug, как `runtime.stop`). `fresh=true` только для следующего стопа после continue/step. Без `debug` прогон блокирующий, как раньше.
- BSL-анализ — MCP bsl-ls: сначала `list_workspace_folders`; при отсутствии корня — `register_workspace_folder` на корень IDE (не `src/cf`).

## Публикация
- `publish.up` / `down` / `status` / `url` — локальный dev-контур проекта (`.1c-dev/publish/`: ibsrv или Apache+webinst). Это не сервер 1С:Предприятие на машине пользователя и не системный IIS/Apache.
- HTTP-сервисы публиковать только через webinst (`backend=webinst` / профиль `local-webinst`). Не через ibsrv.

## Опасное
- `project.clean` — только с `yes=true` после подтверждения. Стирает source, `.1c-dev/runtime/` и `.1c-dev/export/` (EDT XML staging). При `source.path: .` (EDT) wipe source пропускается. Не трогает манифест, AGENTS.md, IDE MCP, git.

## MCP
- `path` = корень scope (родитель `.1c-dev`).
- Nested extension: `extension_id` в metadata.* (id/имя из `configurations[].extensions[]`).
- Standalone extension: только `config_id` (source под `src/cfe/`).
- Write-типы metadata — `doctor` → `supportedTypes` (не перечислять вручную).
<!-- END 1c-dev -->
