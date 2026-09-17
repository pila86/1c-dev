# ADR-006: Project init (bootstrap configuration)

**Статус:** Accepted  
**Дата:** 2026-09-17

## Контекст

Issue #4 и M1 требуют bootstrap пустого проекта конфигурации без Конфигуратора: `1c-dev init --type configuration`. PRD §14 также перечисляет `project init`. Нужен контракт CLI, шаблонов и заполнения `platform.version`.

## Решение

### CLI

- Основная команда: `1c-dev init --type configuration`.
- Алиас: `1c-dev project init` с той же логикой.
- Опции: `--name` (default — sanitized имя cwd или `Configuration`), `--force`.
- M1 поддерживает только `type=configuration`; остальные типы → diagnostic `1CP005`, exit `PROJECT_ERROR` (2).
- Если `1c.project.yaml` уже есть и нет `--force` → `1CP004`, exit 2.

### Шаблоны

Каталог [`templates/configuration/`](../../templates/configuration/) (ADR-002 / PRD §61):

- `1c.project.yaml.tmpl`
- `AGENTS.md` (PRD §44)
- `.gitignore` (`build/`, `.runtime/`, `.cache/`)
- `src/cf/Configuration.xml.tmpl` + `Languages/Русский.xml.tmpl`

При init генерируются UUID; `CompatibilityMode` выводится из версии платформы (`Version8_3_N`). Формат dump — `2.17`.

### Platform version

`platform.version` в манифесте заполняется из `discover_environment()` (major.minor.build). Если платформа не найдена — fallback `8.3.27` (как в fixture ADR-004).

### Пост-проверка

После записи файлов вызывается существующий `validate_project` (только schema манифеста).

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| Только top-level `init` | Совпадает с #4 | Расходится с PRD §14 | Частично: +алиас |
| Вендор cf-init целиком | Проверенный scaffold | Лишняя зависимость/лицензия | Отвергнуто |
| Ждать платформу без fallback | Точнее | Init ломается без 1С | Отвергнуто |

## Последствия

- MCP `project.init` (#6) переиспользует `core.project.init_project`.
- Templates для extension/EPF/ERF — отдельные issues.
- ibcmd load/build (#7) опирается на созданный XML-скелет.

## Связанные решения

- ADR-002, ADR-004, ADR-005
- Issue #4
- PRD §15, §43, §44
