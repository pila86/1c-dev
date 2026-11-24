# 1C Dev Runtime (`1c-dev`)

Agent-independent toolchain и API-слой для AI-native разработки на платформе 1С: CLI + MCP поверх metadata IR, ibcmd, тестов и отладки.

> Agent-independent · IDE-independent · source-format-independent  
> Runtime — фасад над экосистемой 1С, а не её замена.

Полная документация: **[docs/README.md](docs/README.md)**.

## Что умеет

| Область | Возможности |
|---------|-------------|
| Проект | `init` (в т.ч. adopt XML/EDT), манифест `.1c-dev/`, multi-config, extensions |
| Metadata | `list` / `get` / `find` / `create` / `update` / `delete` (IR, 24 write-типа) |
| Source | Designer XML и EDT; `source convert`; break-support |
| Platform | `build`, `check`, import `.cf` / шаблоны tmplts |
| Runtime | Клиент ENTERPRISE, publish (webinst / ibsrv) |
| Tests | YAxUnit: `test discover|run|report`, `yaxunit ensure` |
| Debug | HTTP Debug Protocol (`dbgs`): breakpoints, stack, eval, step |
| Docs | Локальный синтакс-помощник: `docs search|get` |
| AI | MCP stdio + `ide configure` (Cursor / Kilocode) |
| Tools | Внутренний toolchain cache + catalog external tools/services |

## Prerequisites

- [uv](https://docs.astral.sh/uv/) — установка CLI в PATH
- JDK 17+ — `metadata.create` / `update` (xml-gen)
- JDK 21+ — `metadata.list|get|find`, BSL LS; для md-sparrow (EDT write) предпочтителен JDK 25+
- Платформа 1С 8.3.x и `ibcmd` в PATH — build / check / import / integration-тесты
- Опционально: `1cedtcli` (EDT), Docker (часть external tools)

Для разработки monorepo: Python 3.11+ и [Poetry](https://python-poetry.org/).

## Установка

```bash
uv tool install git+https://github.com/pila86/1c-dev
1c-dev toolchain sync
1c-dev doctor
# при отсутствии jars: 1c-dev doctor --fix
```

Снятие: `1c-dev toolchain clean --yes` · `1c-dev uninstall --yes`.

Алиас на переходный период: `1c-dev tools sync` → `toolchain sync`.

## Быстрый старт

```bash
mkdir shop && cd shop
1c-dev init --type configuration
1c-dev configuration add --name Shop
1c-dev metadata create Catalog.Products --synonym "Товары" \
  --attr "Article:String:50:Артикул"
1c-dev docs search "ТаблицаЗначений" --output json
1c-dev build
1c-dev check
```

Adopt уже существующей выгрузки:

```bash
cd existing-xml-or-edt
1c-dev init --type configuration
1c-dev metadata list --output json
```

## Документация

| Документ | Описание |
|----------|----------|
| [docs/README.md](docs/README.md) | Оглавление |
| [User guide](docs/user-guide.md) | Сценарии: init → build → test → debug → tools |
| [CLI reference](docs/cli-reference.md) | Все команды |
| [MCP](docs/mcp.md) | Tools для агентов |
| [ADR](docs/adr/README.md) | Архитектурные решения |
| [Roadmap](docs/roadmap.md) | Статус и follow-ups |
| [CONTRIBUTING](CONTRIBUTING.md) | Разработка в monorepo |

## Локальная разработка

```bash
poetry install
poetry run 1c-dev toolchain sync
poetry run 1c-dev --help
poetry run pytest
poetry run pytest -m integration   # E2E; без platform/jars — skip
```

Перед коммитом: `poetry run ruff check .`, `poetry run mypy`, `poetry run pytest` — см. [CONTRIBUTING](CONTRIBUTING.md).
