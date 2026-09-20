# 1C Dev Runtime

Agent-independent toolchain и API-слой для AI-native разработки на платформе 1С.

## Prerequisites

- Python 3.11+ и [Poetry](https://python-poetry.org/)
- JDK 17+ — для `metadata.create` / `metadata.update` (jar xml-gen)
- JDK 21+ — для `metadata.list` / `get` / `find` (jar md-reader / MDClasses)
- Платформа 1С 8.3.x и `ibcmd` в PATH — для `build` / `check` и integration-тестов

## Стек

- **Язык:** Python 3.11+ ([ADR-001](docs/adr/001-language-core-cli.md))
- **Зависимости:** Poetry
- **CLI:** Typer (`1c-dev`)

## Локальный запуск

```bash
poetry install
./scripts/fetch-xml-gen.sh     # один раз: xml-gen для create/update (JDK 17+)
./scripts/fetch-md-reader.sh   # один раз: md-reader для list/get/find (JDK 21+)
poetry run 1c-dev --version
poetry run 1c-dev --help
poetry run pytest
poetry run pytest -m integration   # E2E с platform/xml-gen/md-reader; иначе skip
```

На Windows: `pwsh scripts/fetch-xml-gen.ps1`, `pwsh scripts/fetch-md-reader.ps1`.

## CLI

Глобально: `--output text|json`, `--version`. Справка по любой команде: `1c-dev <cmd> --help`.

| Команда | Назначение |
|---------|------------|
| `1c-dev doctor` | Проверка окружения (платформа, `ibcmd`, xml-gen, md-reader) |
| `1c-dev init --type configuration` | Bootstrap пустого проекта |
| `1c-dev project detect\|validate\|info` | Манифест `1c.project.yaml` (`project init` = алиас `init`) |
| `1c-dev metadata list` | Список объектов (IR summaries) |
| `1c-dev metadata get <QualifiedName>` | IR объекта по QName |
| `1c-dev metadata find <query>` | Поиск по имени / синониму |
| `1c-dev metadata create <QualifiedName>` | Создать объект в XML (`Catalog` / `Document`, ТЧ) |
| `1c-dev metadata update <QualifiedName>` | Ops над реквизитами Catalog (`add` / `modify` / `remove-attribute`) |
| `1c-dev metadata delete <QualifiedName>` | Удалить объект из source + `Configuration.xml` |
| `1c-dev build [--artifact cf]` | Загрузить XML в file IB через `ibcmd` |
| `1c-dev check [--platform]` | Платформенная проверка конфигурации (`ibcmd config check`) |
| `1c-dev mcp` | MCP server (stdio) для AI-агентов |

Примеры:

```bash
poetry run 1c-dev init --type configuration --output json
poetry run 1c-dev doctor --output json
poetry run 1c-dev metadata create Catalog.Products --synonym "Товары" --attr "Article:String:50:Артикул"
poetry run 1c-dev metadata create Document.Sales --synonym "Продажи" \
  --attr "Comment:String:100:Комментарий" \
  --ts "Products:Товары" --ts-attr "Products.Qty:Number:15.3:Количество"
poetry run 1c-dev metadata update Catalog.Products --op add-attribute --value "Price:Number(15,2)"
poetry run 1c-dev metadata update Catalog.Products --op modify-attribute --value "Price: synonym=Цена, type=Number(10,2)"
poetry run 1c-dev metadata update Catalog.Products --attr "Code:String:20:Код"
poetry run 1c-dev metadata delete Catalog.Products --output json
poetry run 1c-dev metadata list --output json
poetry run 1c-dev metadata get Catalog.Products --output json
poetry run 1c-dev metadata find Товар --output json
poetry run 1c-dev build --output json
poetry run 1c-dev build --artifact cf --output json
poetry run 1c-dev check --output json
poetry run 1c-dev mcp
```

### MCP (Cursor)

Tools: `project.get`, `project.init`, `metadata.create`, `metadata.delete`, `build`, `check` ([ADR-010](docs/adr/010-mcp-architecture.md)).

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
./scripts/fetch-md-reader.sh
poetry run 1c-dev init --type configuration
poetry run 1c-dev doctor
poetry run 1c-dev metadata create Catalog.Products --synonym "Товары"
poetry run 1c-dev metadata update Catalog.Products --attr "Article:String:50:Артикул"
poetry run 1c-dev metadata get Catalog.Products --output json
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
