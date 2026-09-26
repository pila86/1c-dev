# 1C Dev Runtime

Agent-independent toolchain и API-слой для AI-native разработки на платформе 1С.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) — для установки CLI в PATH (`uv tool install`)
- JDK 17+ — для `metadata.create` / `metadata.update` (jar xml-gen)
- JDK 21+ — для `metadata.list` / `get` / `find` (jar md-reader / MDClasses) и BSL LS
- Платформа 1С 8.3.x и `ibcmd` в PATH — для `build` / `check` / `project import` и integration-тестов

Для разработки в monorepo дополнительно: Python 3.11+ и [Poetry](https://python-poetry.org/).

## Стек

- **Язык:** Python 3.11+ ([ADR-001](docs/adr/001-language-core-cli.md))
- **Установка (must):** `uv tool` + user cache toolchain ([ADR-013](docs/adr/013-packaging-toolchain-cache.md))
- **Разработка:** Poetry
- **CLI:** Typer (`1c-dev`)

## Установка (must)

```bash
uv tool install git+https://github.com/pila86/1c-dev
# или из локального wheel: uv tool install ./dist/1c_dev-*.whl

1c-dev --version
1c-dev tools sync          # jars → ~/.cache/1c-dev/tools (Windows: %LOCALAPPDATA%\1c-dev\tools)
1c-dev doctor              # platform, ibcmd, Java, каждый jar toolchain
# при отсутствии jars: 1c-dev doctor --fix
```

Снятие:

```bash
1c-dev tools clean --yes              # только cache
1c-dev uninstall --yes                # cache + uv tool uninstall 1c-dev
```

Override путей jar: `ONEC_XMLGEN_JAR`, `ONEC_MDREADER_JAR`, `ONEC_BSLLS_JAR`, `ONEC_DOCS_FACADE_JAR`.

## Локальная разработка

```bash
poetry install
poetry run 1c-dev tools sync   # предпочтительно вместо ручных fetch-скриптов
poetry run 1c-dev --version
poetry run 1c-dev --help
poetry run pytest
poetry run pytest -m integration   # E2E с platform/xml-gen/md-reader; иначе skip
```

Fallback для разработчиков (те же pin’ы): `./scripts/fetch-xml-gen.sh`, `./scripts/fetch-md-reader.sh` (Windows: `pwsh scripts/fetch-*.ps1`).

## CLI

Глобально: `--output text|json`, `--version`. Справка по любой команде: `1c-dev <cmd> --help`.

| Команда | Назначение |
|---------|------------|
| `1c-dev doctor [--fix]` | Проверка окружения; `--fix` запускает `tools sync` и повторяет проверку |
| `1c-dev tools sync` | Bootstrap jars toolchain в user cache |
| `1c-dev tools clean --yes` | Удалить user cache toolchain |
| `1c-dev uninstall --yes` | Cache + `uv tool uninstall 1c-dev` |
| `1c-dev init --type configuration` | Bootstrap пустого проекта |
| `1c-dev project detect\|validate\|info` | Манифест `1c.project.yaml` (`project init` = алиас `init`) |
| `1c-dev project import --from <file.cf>` | Импорт `.cf` → XML source (`--force` перезаписывает) |
| `1c-dev runtime load --from <file.cf>` | Загрузка `.cf` в file IB без export XML |
| `1c-dev metadata list` | Список объектов (IR summaries) |
| `1c-dev metadata get <QualifiedName>` | IR объекта по QName |
| `1c-dev metadata find <query>` | Поиск по имени / синониму |
| `1c-dev metadata create <QualifiedName>` | Создать объект в XML (`Catalog` / `Document` / `Enum` / регистры) |
| `1c-dev metadata update <QualifiedName>` | Ops над реквизитами / ТЧ Catalog и Document |
| `1c-dev metadata delete <QualifiedName>` | Удалить объект из source + `Configuration.xml` |
| `1c-dev build [--artifact cf]` | Загрузить XML в file IB через `ibcmd` |
| `1c-dev check [--platform]` | Платформенная проверка конфигурации (`ibcmd config check`) |
| `1c-dev mcp` | MCP server (stdio) для AI-агентов |

Примеры:

```bash
1c-dev init --type configuration --output json
1c-dev doctor --output json
1c-dev metadata create Catalog.Products --synonym "Товары" --attr "Article:String:50:Артикул"
1c-dev metadata create Document.Sales --synonym "Продажи" \
  --attr "Comment:String:100:Комментарий" \
  --ts "Products:Товары" --ts-attr "Products.Qty:Number:15.3:Количество"
1c-dev metadata create Enum.OrderStatuses --synonym "Статусы" \
  --value "New:Новый" --value "Done:Выполнен"
1c-dev metadata create InformationRegister.Prices \
  --dimension "Product:Ref:Catalog.Products" \
  --resource "Price:Number:15.2:Цена"
1c-dev metadata update Catalog.Products --op add-attribute --value "Price:Number(15,2)"
1c-dev metadata update Catalog.Products --op modify-attribute --value "Price: synonym=Цена, type=Number(10,2)"
1c-dev metadata update Catalog.Products --attr "Code:String:20:Код"
1c-dev metadata update Document.Sales --ts "Products:Товары" \
  --ts-attr "Products.Qty:Number:15.3:Количество"
1c-dev metadata delete Catalog.Products --output json
1c-dev metadata list --output json
1c-dev metadata get Catalog.Products --output json
1c-dev metadata find Товар --output json
1c-dev build --output json
1c-dev build --artifact cf --output json
1c-dev project import --from build/out/configuration.cf --force --output json
1c-dev runtime load --from build/out/configuration.cf --output json
1c-dev check --output json
1c-dev mcp
```

В Poetry-checkout те же команды через `poetry run 1c-dev …`.

### MCP (Cursor)

Tools: `project.get`, `project.init`, `metadata.list`, `metadata.get`,
`metadata.find`, `metadata.create`, `metadata.update`, `metadata.delete`,
`build`, `check` ([ADR-010](docs/adr/010-mcp-architecture.md)).

Пример `mcp.json` после `uv tool install`:

```json
{
  "mcpServers": {
    "1c-dev": {
      "command": "1c-dev",
      "args": ["mcp"],
      "cwd": "<workspace>"
    }
  }
}
```

Для разработки через Poetry: `"command": "poetry"`, `"args": ["run", "1c-dev", "mcp"]`.

`cwd` должен указывать на корень workspace (или каталог 1С-проекта).

## Текущий фокус

**Milestone M3: Product adopt** — import `.cf`, `uv tool` + `tools sync`, `setup` IDE/агентов, BSL LS MCP и docs (bsl-context).

- [M3 Product adopt](docs/milestones/m3-product-adopt.md)
- [M2: metadata API](docs/milestones/m2-metadata-api.md) (Done)
- [M1 (Done)](docs/milestones/m1-catalog-via-agent.md)
- [Roadmap](docs/roadmap.md)
- [PRD v0.1](1c-dev-runtime-PRD-v0.1.md)

## Быстрый старт

```bash
uv tool install git+https://github.com/pila86/1c-dev
1c-dev tools sync
1c-dev doctor
1c-dev init --type configuration
1c-dev metadata create Catalog.Products --synonym "Товары"
1c-dev metadata update Catalog.Products --attr "Article:String:50:Артикул"
1c-dev metadata get Catalog.Products --output json
1c-dev build
1c-dev check
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
