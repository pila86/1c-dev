# Руководство пользователя

Типовые сценарии (how-to).  
Флаги: `1c-dev <cmd> --help` и [cli-reference.md](cli-reference.md).  
Как устроено и какие зависимости (явные/неявные): [explanation/overview.md](explanation/overview.md), [explanation/dependencies.md](explanation/dependencies.md).

## 1. Установка

```bash
uv tool install git+https://github.com/pila86/1c-dev
1c-dev toolchain sync    # jars / soft-deps в user cache
1c-dev doctor            # или: 1c-dev doctor --fix
```

Кэш toolchain: `~/.cache/1c-dev/tools/` (Windows: `%LOCALAPPDATA%\1c-dev\tools\`).  
Это не external tools (`tools install` / `services`) — они в share, см. [dependencies](explanation/dependencies.md).  
Снятие cache: `1c-dev toolchain clean --yes`; полный uninstall: `1c-dev uninstall --yes`.

## 2. Новый проект конфигурации

```bash
mkdir shop && cd shop
1c-dev init --type configuration
# манифест .1c-dev/project.yaml + IDE MCP (Cursor / Kilocode)
1c-dev configuration add --name Shop
1c-dev metadata create Catalog.Products --synonym "Товары" \
  --attr "Article:String:50:Артикул"
1c-dev build
1c-dev check
```

Пустой `init` создаёт **scope** без объектов. Конфигурацию добавляют `configuration add` или импортом `.cf`.

## 3. Adopt существующего XML / EDT

Если в дереве (depth ≤ 3) уже есть выгрузка Designer XML или EDT-проект:

```bash
cd existing-src
1c-dev init --type configuration
# smart adopt: source.path / format попадают в манифест (ADR-034)
1c-dev project info
1c-dev metadata list --output json
```

## 4. Импорт из `.cf` или шаблона платформы

```bash
1c-dev configuration import --from ./Vendor.cf --force
# или из tmplts:
1c-dev templates list
1c-dev configuration import --from-template <id>
```

Снятие с поддержки без повторного import: `1c-dev source break-support`.

## 5. Расширения

```bash
1c-dev extension add --id custom --name CustomExt
# из .cfe → XML в src/cfe/<id>/:
1c-dev extension add --from ./CustomExt.cfe --name CustomExt
# EDT:
1c-dev extension add --id custom --name CustomExt --format edt
1c-dev build
1c-dev extension list
```

Тестовое расширение (путь вне scope конфигурации) — через `--path` / манифест `configurations[].tests` (см. ADR-029, ADR-034).

## 6. XML ↔ EDT

```bash
1c-dev source convert --to edt
1c-dev source convert --to xml
1c-dev source convert --to edt --extension custom
```

Нужен `1cedtcli` (≥ 2025.1). Build/check при `format: edt` делают export → ibcmd.

## 7. Runtime, publish, docs

```bash
1c-dev runtime start                  # толстый клиент
1c-dev runtime start --client thin
1c-dev runtime start --debug --bp Catalog.Products.ObjectModule:12
1c-dev runtime status
1c-dev runtime stop

1c-dev publish up                     # webinst + user Apache (default)
1c-dev publish up --backend ibsrv
1c-dev publish url
1c-dev publish down

1c-dev docs search "ТаблицаЗначений" --output json
1c-dev docs get "Массив.Добавить" --output json
```

## 8. Тесты (YAxUnit)

```bash
1c-dev toolchain sync                 # soft: YAxUnit.cfe в cache
1c-dev build
1c-dev yaxunit ensure                 # подключить runner в ИБ
1c-dev test discover
1c-dev test run
1c-dev test report
# один тест:
1c-dev test run --filter '...'
```

Exit code **5** — есть падения тестов (не ошибка инфраструктуры).

## 9. Отладка

```bash
1c-dev runtime start --debug --bp CommonModule.SalesServer:Module:10
1c-dev debug wait
1c-dev debug stack
1c-dev debug variables
1c-dev debug eval "Товары.Количество()"
1c-dev debug continue
1c-dev runtime stop
```

С тестами: `1c-dev test run --debug --bp …` → `debug wait` → `test wait`.

## 10. External tools (catalog)

Отдельно от внутреннего toolchain: локальные MCP/сервисы из `catalog/`.

```bash
1c-dev tools list
1c-dev tools install v8std
1c-dev tools install bsl-ls
1c-dev tools install --all
1c-dev services up v8std
1c-dev services up --all
1c-dev services status --all
1c-dev ide configure                  # прописать MCP endpoints
# desire-list проекта: .1c-dev/tools.yaml → tools: [v8std, bsl-ls, …]
1c-dev tools check
```

Устройство: [explanation/dependencies.md](explanation/dependencies.md).  
Углубление: [ADR-033](adr/033-external-tools-manager.md), [CONTRIBUTING](../CONTRIBUTING.md).

## 11. AI-агент (MCP)

После `init` или `ide configure` IDE получает stdio MCP `1c-dev`. Список tools — [mcp.md](mcp.md).

```bash
1c-dev mcp                            # stdio server
1c-dev ide configure --target cursor
```
