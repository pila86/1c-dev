# Справочник CLI

Глобально: `--output text|json`, `--version`. Справка: `1c-dev <группа> <команда> --help`.

В Poetry-checkout: `poetry run 1c-dev …`.  
Зависимости команд (явные/неявные): [explanation/dependencies.md](explanation/dependencies.md).

## Окружение и toolchain

| Команда | Назначение |
|---------|------------|
| `doctor [--fix]` | Диагностика CLI, jars, Java, platform, ibcmd; `--fix` → sync + повтор |
| `toolchain sync` | Скачать/собрать jars и soft-deps в user cache |
| `toolchain clean --yes` | Удалить cache (не трогает installed external tools) |
| `uninstall --yes` | Cache + `uv tool uninstall 1c-dev` |

Override jars: `ONEC_XMLGEN_JAR`, `ONEC_MDREADER_JAR`, `ONEC_BSLLS_JAR`, `ONEC_DOCS_FACADE_JAR`, `ONEC_MDSPARROW_JAR`, `ONEC_YAXUNIT_CFE`, `ONEC_APACHE_HOME`, `ONEC_EDTCLI`.

## Проект и конфигурации

| Команда | Назначение |
|---------|------------|
| `init --type configuration\|extension` | Empty scope или standalone extension; smart adopt XML/EDT; IDE MCP |
| `project detect\|list\|validate\|info` | Манифест `.1c-dev/project.yaml` |
| `project clean --yes` | Wipe `source.path` + `.1c-dev/runtime/` (манифест/IDE intact) |
| `project init` | Алиас `init` |
| `configuration add\|import\|list\|get\|remove\|set-default` | Lifecycle конфигураций |
| `configuration import --from *.cf` | CF → XML source |
| `configuration import --from-template <id>` | CF из tmplts |
| `extension add\|list` | Scaffold / `.cfe` / `--path`; `--format edt` |
| `templates roots\|list\|get` | Каталог шаблонов платформы |
| `source break-support` | Удалить `ParentConfigurations*` |
| `source convert --to edt\|xml` | XML ↔ EDT (+ `--extension`) |

## Metadata (IR)

| Команда | Назначение |
|---------|------------|
| `metadata list\|get\|find` | Чтение IR |
| `metadata create\|update\|delete` | Write (23 Meta DSL + Subsystem) |

Write-типы: AccountingRegister, AccumulationRegister, BusinessProcess, CalculationRegister, Catalog, ChartOfAccounts, ChartOfCalculationTypes, ChartOfCharacteristicTypes, CommonModule, Constant, DataProcessor, DefinedType, Document, DocumentJournal, Enum, EventSubscription, ExchangePlan, HTTPService, InformationRegister, Report, ScheduledJob, **Subsystem**, Task, WebService.

Ссылки в DSL/JSON: `type=Ref` + `reference=Catalog.X` (не `CatalogRef.X`). Список — также `doctor` → `supportedTypes`.

## Build / check / runtime / publish

| Команда | Назначение |
|---------|------------|
| `build [--artifact cf] [--config] [--runtime]` | XML или EDT(export) → file IB (+ nested extensions) |
| `check [--mode Server]` | `ibcmd config check` + Designer `/CheckModules` |
| `runtime load --from *.cf` | CF → IB без XML export |
| `runtime start\|stop\|status` | Клиент ENTERPRISE; `--debug`, `--bp`, `--client thick\|thin` |
| `publish up\|down\|status\|url` | webinst+Apache (default) или `--backend ibsrv` |

## Docs / test / debug

| Команда | Назначение |
|---------|------------|
| `docs search\|get` | Локальный индекс синтакс-помощника (bsl-context) |
| `test discover\|list\|run\|wait\|report` | Test API (YAxUnit) |
| `yaxunit ensure` | Подключить YAXUNIT `.cfe` из cache в ИБ |
| `debug …` | HTTP Debug Protocol: attach/wait/stack/variables/eval/step/… |

Типичный debug-сценарий: `runtime start --debug --bp …` → `debug wait` → `variables`/`eval` → `continue` → `runtime stop`.

## External tools (catalog)

| Команда | Назначение |
|---------|------------|
| `tools list\|info\|install\|check\|remove` | Catalog + share (`~/.local/share/1c-dev/tools/`) |
| `tools sync\|clean` | Deprecated alias → `toolchain …` |
| `services list\|up\|down\|restart\|status\|logs` | Docker compose / process lifecycle |

Catalog: `catalog/v8std`, `catalog/bsl-search`, `catalog/bsl-ls`. Desire-list: `.1c-dev/tools.yaml`.

## IDE / MCP

| Команда | Назначение |
|---------|------------|
| `ide configure [--target all\|cursor\|kilocode\|none]` | MCP, rules, AGENTS.md, `.gitignore` |
| `mcp` | MCP server (stdio) |

См. [mcp.md](mcp.md).
