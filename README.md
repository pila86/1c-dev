# 1C Dev Runtime

Agent-independent toolchain и API-слой для AI-native разработки на платформе 1С.

## Prerequisites

- Python 3.11+ и [Poetry](https://python-poetry.org/)
- JDK 17+ — для `metadata.create` (jar xml-gen)
- Платформа 1С 8.3.x и `ibcmd` в PATH — для `build` / `check` и integration-тестов

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
poetry run pytest -m integration   # E2E с platform/xml-gen; иначе skip
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
| `1c-dev check [--platform]` | Платформенная проверка конфигурации (`ibcmd config check`) |
| `1c-dev mcp` | MCP server (stdio) для AI-агентов |

Примеры:

```bash
poetry run 1c-dev init --type configuration --output json
poetry run 1c-dev doctor --output json
poetry run 1c-dev metadata create Catalog.Products --synonym "Товары" --attr "Article:String:50:Артикул"
poetry run 1c-dev build --output json
poetry run 1c-dev build --artifact cf --output json
poetry run 1c-dev check --output json
poetry run 1c-dev mcp
```

### MCP (Cursor)

Tools M1: `project.get`, `project.init`, `metadata.create`, `build`, `check` ([ADR-010](docs/adr/010-mcp-architecture.md)).

Пример `mcp.json`:

```json
{
  "mcpServers": {
    "1c-dev": {
      "command": "poetry",
      "args": ["run", "1c-dev", "mcp"],
      "cwd": "<workspace>"
    }
  }
}
```

`cwd` должен указывать на корень workspace (или каталог 1С-проекта).

## Текущий фокус

**Milestone M2: metadata API** — list/get/find, update, create для Document и других типов.

- [M2: acceptance criteria](docs/milestones/m2-metadata-api.md)
- [M1 (Done)](docs/milestones/m1-catalog-via-agent.md)
- [Roadmap](docs/roadmap.md)
- [PRD v0.1](1c-dev-runtime-PRD-v0.1.md)

## Быстрый старт

```bash
poetry install
./scripts/fetch-xml-gen.sh
poetry run 1c-dev init --type configuration
poetry run 1c-dev doctor
poetry run 1c-dev metadata create Catalog.Products --synonym "Товары"
poetry run 1c-dev build
poetry run 1c-dev check
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
