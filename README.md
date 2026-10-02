# 1C Dev Runtime

Agent-independent toolchain и API-слой для AI-native разработки на платформе 1С.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) — для установки CLI в PATH (`uv tool install`)
- JDK 17+ — для `metadata.create` / `metadata.update` (jar xml-gen)
- JDK 21+ — для `metadata.list` / `get` / `find` (jar md-reader / MDClasses) и BSL LS
- Платформа 1С 8.3.x и `ibcmd` в PATH — для `build` / `check` / `configuration import` и integration-тестов

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
# M3 accept: poetry run pytest tests/test_m3_acceptance.py -m integration
# publish ibsrv HTTP: poetry run pytest tests/test_publish_integration.py -m integration
# publish webinst: poetry run pytest tests/test_publish_webinst_integration.py -m integration
```

Fallback для разработчиков (те же pin’ы): `./scripts/fetch-xml-gen.sh`, `./scripts/fetch-md-reader.sh` (Windows: `pwsh scripts/fetch-*.ps1`).

## CLI

Глобально: `--output text|json`, `--version`. Справка по любой команде: `1c-dev <cmd> --help`.

| Команда | Назначение |
|---------|------------|
| `1c-dev doctor [--fix]` | Проверка окружения; `--fix` запускает `tools sync` и повторяет проверку |
| `1c-dev tools sync` | Bootstrap jars + user Apache (`tools/apache`) в cache |
| `1c-dev tools clean --yes` | Удалить user cache toolchain |
| `1c-dev uninstall --yes` | Cache + `uv tool uninstall 1c-dev` |
| `1c-dev init --type configuration [--ide-target all\|cursor\|kilocode\|none]` | Bootstrap пустого проекта конфигурации (+ IDE MCP) |
| `1c-dev init --type extension` | Bootstrap standalone-проекта расширения (`src/cfe/<name>/`) |
| `1c-dev extension add [--id] [--name] [--purpose] [--from *.cfe] [--config]` | Добавить расширение (XML scaffold или выгрузка XML из `.cfe`) |
| `1c-dev extension list [--config] [--runtime]` | Список расширений в выбранной file IB |
| `1c-dev templates roots\|list\|get` | Каталог шаблонов платформы (tmplts / `*.mft`) |
| `1c-dev project detect\|validate\|info` | Манифест `.1c-dev/project.yaml` (`project init` = алиас `init`) |
| `1c-dev configuration import --from <file.cf>` | Импорт `.cf` → XML source (`--force` перезаписывает; `--break-support` снимает с поддержки) |
| `1c-dev configuration import --from-template <id>` | Импорт `.cf` из шаблона платформы (tmplts; id из `templates.list`) |
| `1c-dev configuration add\|list\|get\|remove\|set-default` | Lifecycle конфигураций в scope |
| `1c-dev source break-support` | Удалить `ParentConfigurations*` из `source.path` (без повторного import) |
| `1c-dev project clean --yes` | Destructive: wipe `source.path` + `.1c-dev/runtime/` (манифест/IDE intact) |
| `1c-dev runtime load --from <file.cf>` | Загрузка `.cf` в file IB без export XML |
| `1c-dev runtime start [--client thick|thin] [--debug]` | Запуск клиента (ENTERPRISE) к file IB |
| `1c-dev runtime stop` | Остановка клиента |
| `1c-dev runtime status` | Статус клиента (pid / client / debug) |
| `1c-dev publish up [--profile] [--backend]` | Публикация file IB (default: `webinst`+user Apache; опционально `ibsrv`); `--backend` создаёт `local-*` профиль при необходимости |
| `1c-dev publish down [--profile] [--backend]` | Остановка publish-backend (`ibsrv` / httpd) |
| `1c-dev publish status\|url [--profile] [--backend]` | Статус / URL веб-клиента |
| `1c-dev metadata list` | Список объектов (IR summaries) |
| `1c-dev metadata get <QualifiedName>` | IR объекта по QName |
| `1c-dev metadata find <query>` | Поиск по имени / синониму |
| `1c-dev metadata create <QualifiedName>` | Создать объект (23 Meta DSL + `Subsystem`) |
| `1c-dev metadata update <QualifiedName>` | Ops над существующим объектом (те же write-типы) |
| `1c-dev metadata delete <QualifiedName>` | Удалить объект из source + `Configuration.xml` |
| `1c-dev build [--artifact cf] [--config] [--runtime]` | Загрузить configuration (+ nested extensions XML/`.cfe`) в file IB через `ibcmd` |
| `1c-dev check [--platform]` | Платформенная проверка конфигурации (`ibcmd config check`) |
| `1c-dev mcp` | MCP server (stdio) для AI-агентов |
| `1c-dev ide configure [--project] [--ide-root] [--agents] [--target …]` | AGENTS.md (merge), `.gitignore`, IDE MCP + rules |

**Write-типы** (`metadata.create` / `update` / `delete`; также `doctor` → `supportedTypes`, [ADR-018](docs/adr/018-metadata-types-coverage.md)): AccountingRegister, AccumulationRegister, BusinessProcess, CalculationRegister, Catalog, ChartOfAccounts, ChartOfCalculationTypes, ChartOfCharacteristicTypes, CommonModule, Constant, DataProcessor, DefinedType, Document, DocumentJournal, Enum, EventSubscription, ExchangePlan, HTTPService, InformationRegister, Report, ScheduledJob, **Subsystem**, Task, WebService.

Примеры:

```bash
1c-dev init --type configuration --output json
1c-dev extension add --id custom --name CustomExt
# или из готового .cfe (выгрузка XML в src/cfe/<id>/, не копирование бинарника):
# 1c-dev extension add --from ./CustomExt.cfe --name CustomExt
1c-dev build   # configuration, затем extensions → default runtime IB
1c-dev extension list
```

```bash
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
1c-dev metadata create CommonModule.SalesServer --server --server-call
1c-dev metadata create Subsystem.Sales --synonym "Продажи" \
  --content Catalog.Products --content Document.Sales
1c-dev metadata create Constant.VATRate --value-type Number:15.2
1c-dev metadata create DefinedType.CounterpartyRef --value-type "Ref:Catalog.Products"
1c-dev metadata create Report.SalesReport --synonym "Отчёт"
1c-dev metadata create ScheduledJob.Cleanup --method-name CommonModule.SalesServer.Cleanup
1c-dev metadata create EventSubscription.ProductsBeforeWrite \
  --handler CommonModule.SalesServer.BeforeWrite --event BeforeWrite \
  --source Catalog.Products
1c-dev metadata update Catalog.Products --op add-attribute --value "Price:Number(15,2)"
1c-dev metadata update Catalog.Products --op modify-attribute --value "Price: synonym=Цена, type=Number(10,2)"
1c-dev metadata update Catalog.Products --attr "Code:String:20:Код"
1c-dev metadata update Document.Sales --ts "Products:Товары" \
  --ts-attr "Products.Qty:Number:15.3:Количество"
1c-dev metadata update Subsystem.Sales --op add-content --value Catalog.Products
1c-dev metadata delete Catalog.Products --output json
1c-dev metadata delete Subsystem.Sales --output json
1c-dev metadata list --output json
1c-dev metadata get Catalog.Products --output json
1c-dev metadata find Товар --output json
1c-dev build --output json
1c-dev build --artifact cf --output json
1c-dev configuration import --from build/out/configuration.cf --force --output json
1c-dev project clean --yes --output json
1c-dev runtime load --from build/out/configuration.cf --output json
1c-dev runtime start --output json
1c-dev runtime start --client thin --output json
1c-dev runtime start --debug --output json
1c-dev runtime status --output json
1c-dev runtime stop --output json
1c-dev publish up --output json
1c-dev publish up --backend ibsrv --output json
1c-dev publish status --output json
1c-dev publish url
1c-dev publish down --output json
1c-dev check --output json
1c-dev ide configure --output json
1c-dev ide configure --target cursor --output json
1c-dev ide configure --target none --output json
1c-dev ide configure --project products/shop --ide-root . --agents scope --output json
1c-dev mcp
```

В Poetry-checkout те же команды через `poetry run 1c-dev …`.

### MCP (Cursor / Kilocode)

После `1c-dev init` MCP-конфиги пишутся сразу (default `--ide-target all`).
Для уже существующего проекта (после `import` / clone):

```bash
1c-dev ide configure                 # MCP для cursor и kilocode (default --target all)
# или: 1c-dev ide configure --target cursor
# monorepo: MCP в корне workspace, scope nested
# 1c-dev ide configure --project products/shop --ide-root . --agents scope
```

Tools: `project.get`, `project.init`, `ide.configure`, `configuration.import`,
`configuration.add` / `list` / `get` / `remove` / `set-default`, `project.clean`,
`metadata.list`, `metadata.get`, `metadata.find`, `metadata.create`,
`metadata.update`, `metadata.delete`, `build`, `check`,
`runtime.start`, `runtime.stop`, `runtime.status`,
`publish.up`, `publish.down`, `publish.status`, `publish.url`,
`templates.roots`, `templates.list`, `templates.get`,
`docs.search`, `docs.get`
([ADR-010](docs/adr/010-mcp-architecture.md), [ADR-016](docs/adr/016-ide-configure.md),
[ADR-019](docs/adr/019-runtime-client-lifecycle.md), [ADR-021](docs/adr/021-project-clean.md),
[ADR-024](docs/adr/024-platform-templates.md),
[ADR-028](docs/adr/028-configuration-import.md)).
`project.clean` — destructive (нужен `yes=true`); не трогает манифест / IDE / git.`metadata.create` / `update` / `delete` покрывают те же 24 write-типа, что и CLI
(список — в описании tool и в `doctor` → `supportedTypes`).

Пример `.cursor/mcp.json` (пишет `init` / `ide configure`; `cwd` не нужен — IDE стартует из workspace):

```json
{
  "mcpServers": {
    "1c-dev": {
      "command": "1c-dev",
      "args": ["mcp"]
    },
    "bsl-language-server": {
      "command": "java",
      "args": ["-jar", "/path/to/bsl-language-server.jar", "mcp"]
    }
  }
}
```

Для разработки через Poetry: `"command": "poetry"`, `"args": ["run", "1c-dev", "mcp"]`.

Kilocode: тот же формат в `.kilo/mcp.json`.

## Текущий фокус

**Milestone M3: Product adopt** — import `.cf`, `uv tool` + `tools sync`, `ide configure`, BSL LS MCP и docs (bsl-context).

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
1c-dev docs search "ТаблицаЗначений" --output json
1c-dev docs get "Массив.Добавить" --output json
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
