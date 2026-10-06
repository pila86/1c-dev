<!-- BEGIN 1c-dev -->
# Правила 1c-dev

## Запреты
- Не править generated artifacts; уважать source format проекта.
- Не выгружать конфигурацию вручную через Конфигуратор.
- Не выдумывать API платформы — только `docs.search` / `docs.get`.

## Порядок
- Предпочитать MCP `1c-dev` и `bsl-language-server`, не shell и не Конфигуратор.
- Greenfield: `project.init` → `configuration.add` → `project.get` → metadata.* / build.
- `project.init` создаёт только home (пустые `configurations[]` / `runtimes[]`), не XML.
- После правок: check → build → `test.*` (цикл `build → test.run` перед завершением задачи).
- Тесты: MCP `test.discover` / `test.list` / `test.run` / `test.runOne` / `test.report` или CLI `1c-dev test` (не сторонний MCP runner).
- Перед завершением задачи — semantic diff.
- Воспроизводимые runtime-сбои — debugger.
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
