# 1C Dev Runtime

Agent-independent toolchain и API-слой для AI-native разработки на платформе 1С.

## Стек

- **Язык:** Python 3.11+ ([ADR-001](docs/adr/001-language-core-cli.md))
- **Зависимости:** Poetry
- **CLI:** Typer (`1c-dev`)

## Локальный запуск

```bash
poetry install
./scripts/fetch-xml-gen.sh   # один раз: xml-gen для metadata.create (JDK 17+)
poetry run 1c-dev --version
poetry run 1c-dev --help
poetry run pytest
```

На Windows: `pwsh scripts/fetch-xml-gen.ps1`.

## CLI

Глобально: `--output text|json`, `--version`. Справка по любой команде: `1c-dev <cmd> --help`.

| Команда | Назначение |
|---------|------------|
| `1c-dev doctor` | Проверка окружения (платформа, `ibcmd`) |
| `1c-dev init --type configuration` | Bootstrap пустого проекта |
| `1c-dev project detect\|validate\|info` | Манифест `1c.project.yaml` (`project init` = алиас `init`) |
| `1c-dev metadata create <QualifiedName>` | Создать объект метаданных в XML (M1: Catalog) |
| `1c-dev build [--artifact cf]` | Загрузить XML в file IB через `ibcmd` |

Примеры:

```bash
poetry run 1c-dev init --type configuration --output json
poetry run 1c-dev doctor --output json
poetry run 1c-dev metadata create Catalog.Products --synonym "Товары" --attr "Article:String:50:Артикул"
poetry run 1c-dev build --output json
poetry run 1c-dev build --artifact cf --output json
```

Ещё не реализовано: `1c-dev check` (#9), `1c-dev mcp` (#6).

## Текущий фокус

**Milestone M1: catalog via agent** — агент создаёт конфигурацию с одним справочником через MCP без ручного Конфигуратора.

- [M1: acceptance criteria и workflow](docs/milestones/m1-catalog-via-agent.md)
- [Roadmap](docs/roadmap.md)
- [Milestone M1 на GitHub](https://github.com/pila86/1c-dev/milestone/1)
- [PRD v0.1](1c-dev-runtime-PRD-v0.1.md)

### Issues M1

| # | Задача |
|---|--------|
| [#1](https://github.com/pila86/1c-dev/issues/1) | ADR и каркас monorepo |
| [#2](https://github.com/pila86/1c-dev/issues/2) | Project manifest и project API |
| [#3](https://github.com/pila86/1c-dev/issues/3) | Doctor: discovery окружения |
| [#4](https://github.com/pila86/1c-dev/issues/4) | Project init: пустая configuration |
| [#5](https://github.com/pila86/1c-dev/issues/5) | Metadata IR v0 + metadata.create |
| [#6](https://github.com/pila86/1c-dev/issues/6) | MCP server: agent-facing tools |
| [#7](https://github.com/pila86/1c-dev/issues/7) | Platform adapter: ibcmd build |
| [#8](https://github.com/pila86/1c-dev/issues/8) | Acceptance test M1 |
| [#9](https://github.com/pila86/1c-dev/issues/9) | Check: platform check |
| [#10](https://github.com/pila86/1c-dev/issues/10) | README и developer onboarding |

## Быстрый старт

```bash
poetry install
./scripts/fetch-xml-gen.sh
poetry run 1c-dev init --type configuration
poetry run 1c-dev doctor
poetry run 1c-dev metadata create Catalog.Products --synonym "Товары"
poetry run 1c-dev build
```

## Документация

| Документ | Описание |
|----------|----------|
| [PRD v0.1](1c-dev-runtime-PRD-v0.1.md) | Полная спецификация |
| [Roadmap](docs/roadmap.md) | Этапы разработки |
| [CONTRIBUTING](CONTRIBUTING.md) | Как участвовать |
| [ADR](docs/adr/README.md) | Архитектурные решения |

## Принцип

> Agent-independent + IDE-independent + source-format-independent.

Runtime — фасад над существующей 1С developer ecosystem, а не её замена.
