# 1c-dev

Инструментарий (CLI + MCP) для AI-native разработки на платформе 1С. Работает с метаданными через единую модель, собирает и проверяет конфигурацию средствами платформы, запускает тесты и отладку.

Не зависит от конкретного агента, IDE или формата исходников. Это оркестратор над платформой 1С и вспомогательными инструментами, а не их замена.
Не дублируем то, что уже сделано в сообществе 1С: подключаем проверенные проекты и делаем над ними единый CLI и MCP.

Документация: [docs/README.md](docs/README.md).  
Как устроено: [обзор](docs/explanation/overview.md) · [зависимости](docs/explanation/dependencies.md).

## Возможности

| Область | Что делает |
|---------|------------|
| Проект | Создаёт манифест `.1c-dev/`, подключает существующую выгрузку XML или EDT, ведёт несколько конфигураций и расширений |
| Метаданные | Читает и изменяет объекты (`list`, `get`, `find`, `create`, `update`, `delete`); 24 типа объектов на запись |
| Исходники | Форматы XML (Конфигуратор) и EDT; конвертация (`source convert`); снятие с поддержки |
| Сборка | Загрузка в файловую ИБ (`build`), платформенная проверка (`check`), импорт `.cf` и шаблонов платформы |
| Клиент и публикация | Запуск клиента 1С; публикация ИБ через webinst или ibsrv |
| Тесты | Прогон YAxUnit (`test …`, `yaxunit ensure`) |
| Отладка | Точки останова, стек, вычисление выражений, шаг по HTTP Debug Protocol (`dbgs`) |
| Справка платформы | Локальный синтакс-помощник (`docs search`, `docs get`) |
| IDE и агенты | Настройка MCP для Cursor и Kilocode (`ide configure`) |
| Внешние инструменты | Каталог и сервисы (например v8std, bsl-ls); отдельно — кэш внутренних jar |

## Что нужно установить

Обязательно:

- [uv](https://docs.astral.sh/uv/) — чтобы поставить `1c-dev` в PATH
- JDK 25+ — единый для jar toolchain (xml-gen, md-reader, docs-facade, md-sparrow)
- Платформа 1С 8.3.x и утилита `ibcmd` в PATH — сборка, проверка, импорт

По желанию:

- `1cedtcli` — работа с проектами EDT
- Docker — часть внешних инструментов из каталога

Для разработки самого репозитория: Python 3.11+ и [Poetry](https://python-poetry.org/).

## Установка

```bash
uv tool install git+https://github.com/pila86/1c-dev
1c-dev toolchain sync
1c-dev doctor
# если не хватает jar: 1c-dev doctor --fix
```

Удалить кэш зависимостей: `1c-dev toolchain clean --yes`.  
Снять CLI из PATH вместе с кэшем: `1c-dev uninstall --yes`.

Пока поддерживается старое имя: `1c-dev tools sync` (то же, что `toolchain sync`).

## Быстрый старт

Новый проект:

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

Уже есть выгрузка XML или проект EDT:

```bash
cd путь-к-выгрузке
1c-dev init --type configuration
1c-dev metadata list --output json
```

## Cursor и Kilocode

Агент в IDE ходит в `1c-dev` через MCP (stdio), а не через shell «вслепую».

1. Установите CLI (`uv tool install` + `toolchain sync`), чтобы команда `1c-dev` была в PATH.
2. В корне проекта:
   - новый scope: `1c-dev init` — сразу пишет MCP-конфиг (по умолчанию Cursor и Kilocode);
   - уже есть манифест / clone: `1c-dev ide configure`.
3. Откройте папку как workspace в Cursor или Kilocode и перезапустите MCP, если IDE уже была открыта.

Что появляется в проекте:

| IDE | MCP | Rules / подсказки агенту |
|-----|-----|---------------------------|
| Cursor | `.cursor/mcp.json` | `.cursor/rules/`, `AGENTS.md` |
| Kilocode | `.kilo/mcp.json` | `.kilo/rules/`, `AGENTS.md` |

Только одна IDE: `1c-dev ide configure --target cursor` или `--target kilocode`.  
Без MCP: `--target none`.

Минимальный MCP-сервер (его же пишет `ide configure`):

```json
{
  "mcpServers": {
    "1c-dev": {
      "command": "1c-dev",
      "args": ["mcp"]
    }
  }
}
```

Дальше агент вызывает MCP tools (`metadata.*`, `build`, `check`, `test.*`, …) — список в [docs/mcp.md](docs/mcp.md).  
Внешние MCP (`bsl-ls`, `v8std`, …) — см. ниже.

## Внешние инструменты

Это не `toolchain sync` (внутренние jar), а каталог `catalog/` — отдельные MCP и сервисы. Установка ≠ запуск. Для части стеков нужен Docker.

Поставить всё из каталога и поднять сервисы:

```bash
1c-dev tools list
1c-dev tools install --all
1c-dev services up --all
1c-dev services status --all
1c-dev ide configure          # прописать MCP endpoints в IDE
1c-dev doctor
```

Сейчас в каталоге: `v8std`, `bsl-ls`, `bsl-search`.  
`services up --all` поднимает только уже установленные managed-сервисы; неустановленные пропускает с предупреждением.

По одному:

```bash
1c-dev tools install v8std
1c-dev services up v8std
```

Без сети (только файлы из catalog, без pull образов/jar): `1c-dev tools install --all --no-pull`.

Остановка: `1c-dev services down --all`.  
Желаемый набор для проекта (не создаётся `init`): `.1c-dev/tools.yaml` → `1c-dev tools check`.

Устройство и зависимости (toolchain ≠ catalog, явное/неявное):  
[обзор](docs/explanation/overview.md) · [зависимости](docs/explanation/dependencies.md) · [ADR-033](docs/adr/033-external-tools-manager.md).

## Документация

| Документ | Содержание |
|----------|------------|
| [Оглавление](docs/README.md) | Карта по задачам читателя |
| [Как устроено](docs/explanation/overview.md) | Слои, границы, toolchain vs external tools |
| [Зависимости](docs/explanation/dependencies.md) | Явное / неявное / soft, пути на диске |
| [Руководство](docs/user-guide.md) | Типовые сценарии |
| [Справочник CLI](docs/cli-reference.md) | Команды по группам |
| [MCP](docs/mcp.md) | Подключение к IDE и список MCP tools |
| [ADR](docs/adr/README.md) | Почему так решили (углубление) |
| [План](docs/roadmap.md) | Статус и открытые задачи |
| [Участие в разработке](CONTRIBUTING.md) | Работа с репозиторием |

## Разработка в репозитории

```bash
poetry install
poetry run 1c-dev toolchain sync
poetry run 1c-dev --help
poetry run pytest
poetry run pytest -m integration   # нужны платформа и jar; иначе тесты пропускаются
```

Перед коммитом: `poetry run ruff check .`, `poetry run mypy`, `poetry run pytest` — подробности в [CONTRIBUTING](CONTRIBUTING.md).

## Благодарности

`1c-dev` опирается на экосистему 1С и открытые проекты сообщества. Спасибо авторам и мейнтейнерам:

- [MDClasses](https://github.com/1c-syntax/mdclasses), [bsl-context](https://github.com/1c-syntax/bsl-context), [BSL Language Server](https://github.com/1c-syntax/bsl-language-server)
- [xml-gen](https://github.com/SteelMorgan/1c-agent-based-dev-framework/tree/master/tools/xml-gen) (SteelMorgan), [md-sparrow](https://github.com/yellow-hammer/md-sparrow)
- [YaXUnit](https://github.com/bia-technologies/yaxunit)
- [v8std](https://github.com/zeegin/v8std), [mcp-bsl-search](https://github.com/axel-avb/mcp-bsl-search)

Платформа 1С и 1C:EDT — внешняя основа для сборки, ИБ и EDT-сценариев.

Роли компонентов и как они подключаются: [docs/explanation/dependencies.md](docs/explanation/dependencies.md).
