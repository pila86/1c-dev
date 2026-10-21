<!-- BEGIN 1c-dev -->
# Правила 1c-dev

## Запреты
- Не читать и не править исходники инструмента `1c-dev` (репозиторий, пакет, внутренности CLI/MCP).
- Не править generated artifacts; уважать source format проекта.
- Не выгружать конфигурацию вручную через Конфигуратор.
- Не выдумывать API платформы — только `docs.search` / `docs.get`.

## Порядок
- Предпочитать MCP `1c-dev` и `bsl-language-server`, не shell и не Конфигуратор.
- Если нужной операции нет в MCP/CLI или она не закрывает задачу — допустимо править исходники конфигурации/расширения напрямую (BSL, XML и т.п. в source.path). После этого — тот же цикл: diagnostics → build → check → test.
- Greenfield: `project.init` → `configuration.add` → `project.get` → metadata.* / build.
- `project.init` создаёт только home (пустые `configurations[]` / `runtimes[]`), не XML.
- После правок BSL: diagnostics (bsl-ls) → build → check → `test.*`. `check` — по file IB после `build`.
- Тесты: MCP `test.discover` / `test.list` / `test.run` / `test.runOne` / `test.wait` / `test.report` или CLI `1c-dev test` (не сторонний MCP runner).
- Перед завершением задачи — semantic diff.
- Воспроизводимые **runtime**-сбои (не вместо `test.*`): MCP `debug.*` / CLI `1c-dev debug` (не shell, не Конфигуратор, не сторонний debug MCP). Doctor soft gap `debug.http` (dbgs + порт).
- Debug-цикл (runtime): `debug.server.start` (если нужно) → `runtime.start` с `--debug` (или `--bp`) → `debug.attach` → breakpoint → действие → `debug.wait` → `debug.variables` / `debug.evaluate` → fix → `debug.continue` / `detach`. Коротко: «сломалось на строке N → vars → fix».
- Debug упавшего теста: `test.run` / `test.runOne` с `debug=true` и `breakpoints` → `status: running` → `debug.wait` → vars/eval/continue → `test.wait` (jUnit + teardown debug, как `runtime.stop`). Без `debug` прогон блокирующий, как раньше.
- BSL-анализ — MCP bsl-ls: сначала `list_workspace_folders`; при отсутствии корня — `register_workspace_folder` на корень IDE (не `src/cf`).

## Публикация
- `publish.up` / `down` / `status` / `url` — локальный dev-контур проекта (`.1c-dev/publish/`: ibsrv или Apache+webinst). Это не сервер 1С:Предприятие на машине пользователя и не системный IIS/Apache.
- HTTP-сервисы публиковать только через webinst (`backend=webinst` / профиль `local-webinst`). Не через ibsrv.

## Опасное
- `project.clean` — только с `yes=true` после подтверждения. Стирает source и `.1c-dev/runtime/`. Не трогает манифест, AGENTS.md, IDE MCP, git.

## MCP
- `path` = корень scope (родитель `.1c-dev`).
- Nested extension: `extension_id` в metadata.* (id/имя из `configurations[].extensions[]`).
- Standalone extension: только `config_id` (source под `src/cfe/`).
- Write-типы metadata — `doctor` → `supportedTypes` (не перечислять вручную).
<!-- END 1c-dev -->
