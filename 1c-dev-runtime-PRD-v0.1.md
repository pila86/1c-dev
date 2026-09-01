# 1C Dev Runtime — PRD / Техническое задание v0.1

**Статус:** Draft for Architecture & Development  
**Версия спецификации:** 0.1  
**Дата:** 2026-09-01  
**Назначение:** создание агент-независимой инфраструктуры AI-native разработки на 1С

---

## 1. Резюме

`1C Dev Runtime` — локальный/удалённый toolchain и API-слой для разработки на платформе 1С, предназначенный прежде всего для работы AI coding agents.

Цель проекта — дать любому агенту (Codex, Claude Code, Cursor, Kilo Code, IDE-плагины, собственные агенты и т.д.) единый способ:

- читать и изменять исходники 1С;
- работать с несколькими форматами исходников;
- понимать BSL;
- понимать структуру метаданных;
- читать справку конкретной версии платформы;
- создавать конфигурации, расширения и внешние обработки/отчёты;
- собирать проект;
- создавать и управлять тестовой информационной базой;
- запускать проверки и тесты;
- запускать приложение;
- подключаться к отладчику;
- получать структурированные результаты операций;
- выполнять весь основной цикл разработки без интерактивного Конфигуратора.

Проект **не является IDE**, **не является AI-агентом**, **не заменяет BSL Language Server**, **не заменяет 1С:Предприятие**, **не заменяет тестовые фреймворки**.

Главный принцип:

> **Agent-independent + IDE-independent + source-format-independent.**

---

# 2. Проблема

Современная AI-разработка на 1С возможна, но инфраструктура фрагментирована.

Сегодня разработчик вынужден самостоятельно комбинировать:

- BSL Language Server;
- `ibcmd`;
- `1cv8`;
- 1C:EDT CLI;
- конвертеры исходников;
- парсеры метаданных;
- парсеры справки;
- YAxUnit;
- Vanessa;
- отладчики;
- VS Code extensions;
- MCP servers;
- shell scripts;
- собственные AGENTS.md/rules/skills.

Разные энтузиасты используют разные комбинации.

Следствия:

1. агент зависит от конкретного IDE;
2. агент зависит от конкретного набора shell-команд;
3. исходники могут быть представлены в разных форматах;
4. отсутствует единый API для работы с проектом;
5. результаты команд часто возвращаются в неструктурированном виде;
6. AI приходится читать XML/EDT-файлы вместо работы с семантической моделью;
7. отсутствует единый lifecycle `change → check → build → test → debug`;
8. создание новых проектов требует ручных действий;
9. диагностика окружения сложна;
10. перенос проекта между агентами и средами затруднён.

---

# 3. Цели

## 3.1. Основные цели

### G1. Независимость от AI-агента

Один и тот же проект и runtime должны использоваться с:

- Codex;
- Claude Code;
- Cursor;
- Kilo Code;
- VS Code;
- другими MCP/LSP/DAP-compatible клиентами;
- собственными агентами.

### G2. Независимость от IDE

Основной workflow не должен требовать:

- Конфигуратора;
- интерактивной 1С:EDT;
- конкретного IDE.

IDE могут использоваться как optional clients.

### G3. Независимость от формата исходников

Runtime должен поддерживать несколько source formats через adapter architecture.

Первичные кандидаты:

- XML source;
- EDT source.

Архитектура должна позволять добавлять новые форматы без изменения верхнего API.

### G4. Минимум ручных операций

Разработчик не должен вручную выполнять:

- выгрузку конфигурации в XML;
- загрузку XML;
- создание ИБ через GUI;
- запуск тестов через GUI;
- переключение между IDE для выполнения служебных операций.

### G5. Agent-friendly API

Все ключевые операции должны быть доступны:

- через CLI;
- через machine-readable JSON;
- через MCP.

### G6. Platform-aware development

Runtime должен учитывать конкретную версию платформы 1С и использовать соответствующую документацию и capabilities.

### G7. Reuse existing ecosystem

Не реализовывать заново то, что уже качественно реализовано:

- BSL parser;
- BSL LSP;
- documentation parser;
- metadata parser;
- test frameworks;
- debugger.

---

# 4. Не цели

В scope v0.1 не входят:

- собственная IDE;
- собственный BSL compiler;
- собственный BSL parser;
- собственный полноценный debugger;
- собственный test framework;
- собственный формат конфигурации как обязательный source format;
- замена 1С:Предприятия;
- замена 1С:EDT;
- облачная CI/CD платформа;
- автономный AI agent.

---

# 5. Архитектурные принципы

## P1. Agent-independent

Agent является клиентом runtime.

```text
Codex ────────┐
Claude Code ──┤
Cursor ───────┼──► 1C Dev Runtime
Kilo ─────────┤
Custom Agent ─┘
```

## P2. IDE-independent

VS Code, EDT и другие IDE — клиенты, а не фундамент архитектуры.

## P3. Source-format-independent

XML и EDT — реализации Source Adapter API.

## P4. Standards-first

Использовать существующие стандарты:

- MCP;
- LSP;
- DAP;
- Git;
- JSON Schema.

## P5. Reuse-first

Предпочтительно интегрировать существующие проекты, а не переписывать их.

## P6. Semantic-first

AI должен работать преимущественно с:

- metadata;
- symbols;
- references;
- dependencies;
- documentation;

а не с сырыми XML-файлами.

## P7. Machine-readable first

Каждая команда должна иметь структурированный результат.

## P8. Version-aware

Версия платформы — обязательная часть project context.

## P9. Capability-driven

Не все source/runtime backends поддерживают одинаковые операции. Возможности должны описываться через capabilities.

## P10. Zero-manual-export

Для поддерживаемых форматов source↔runtime sync должен выполняться автоматически.

---

# 6. Высокоуровневая архитектура

```text
                       ┌──────────────────────────┐
                       │        AI Agent          │
                       │                          │
                       │ Codex / Claude / Cursor  │
                       │ Kilo / IDE / Custom     │
                       └────────────┬─────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    │               │               │
                   MCP             LSP             DAP
                    │               │               │
                    ▼               ▼               ▼
            ┌──────────────────────────────────────────┐
            │             1C Dev Runtime               │
            │                                          │
            │ Project API                              │
            │ Source API                               │
            │ Metadata API                             │
            │ BSL API                                  │
            │ Documentation API                        │
            │ Build API                                │
            │ Test API                                 │
            │ Runtime API                              │
            │ Debug API                                │
            │ Diff / Impact API                        │
            └────────────────────┬─────────────────────┘
                                 │
             ┌───────────────────┼────────────────────┐
             │                   │                    │
             ▼                   ▼                    ▼
      Source Adapters     Platform Adapters     Intelligence
             │                   │                    │
       ┌─────┴─────┐       ┌─────┼─────┐        ┌────┴─────┐
       │           │       │     │     │        │          │
      XML          EDT    ibcmd  1cv8  EDT CLI   BSL LS   Docs
                                                     │     Index
             │                   │                    │
             └───────────────────┼────────────────────┘
                                 ▼
                           1C Platform
```

---

# 7. Компоненты

## 7.1. `1c-dev-cli`

Единая командная строка.

Назначение:

- управление проектом;
- диагностика окружения;
- source operations;
- build;
- check;
- test;
- runtime;
- debug;
- docs;
- metadata;
- diff;
- verify.

---

## 7.2. `1c-dev-core`

Ядро runtime.

Отвечает за:

- project model;
- configuration resolution;
- adapter discovery;
- capability resolution;
- execution lifecycle;
- structured diagnostics;
- process management;
- configuration of external tools.

---

## 7.3. Source Adapter Layer

Абстрагирует физический формат исходников.

Первые реализации:

- `XmlSourceAdapter`;
- `EdtSourceAdapter`.

---

## 7.4. Platform Adapter Layer

Абстрагирует конкретные механизмы взаимодействия с платформой.

Кандидаты:

- `ibcmd`;
- `1cv8`;
- `1cedtcli`.

---

## 7.5. Metadata Service

Предоставляет семантическую модель метаданных поверх существующих parser/converter-инструментов.

---

## 7.6. Documentation Service

Индексирует локальную справку конкретных версий платформы.

---

## 7.7. BSL Integration

Интеграция с BSL Language Server и BSL Parser.

---

## 7.8. Test Runner Adapters

Минимум:

- YAxUnit;
- Vanessa Runner.

Архитектура должна позволять добавлять:

- OneUnit;
- 1testrunner;
- другие runners.

---

## 7.9. Debug Adapter

Интеграция с существующим DAP debugger для 1С.

---

## 7.10. MCP Server

Единый agent-facing MCP server.

---

# 8. Project Model

Проект описывается manifest-файлом:

```text
1c.project.yaml
```

Пример:

```yaml
schema: "1"

project:
  name: shop
  type: configuration

platform:
  version: "8.3.27"

source:
  format: xml
  path: src/cf

runtime:
  type: file
  path: .runtime/ib

artifacts:
  directory: build/out

tests:
  unit:
    runner: yaxunit
    path: tests/unit

  bdd:
    runner: vanessa
    path: features

tools:
  docs:
    source: platform

  debug:
    adapter: bsl-debug-server
```

---

# 9. Project Types

Минимально поддержать:

```text
configuration
extension
external-data-processor
external-report
```

В будущем возможно:

```text
external-addin
common-project
library
```

---

# 10. Source Formats

## 10.1. Обязательные для архитектуры

```text
xml
edt
```

## 10.2. Артефакты

Следующие форматы не считаются source formats:

```text
cf
cfe
epf
erf
```

Они являются artifacts.

Модель:

```text
Source → Build → Artifact
```

---

# 11. Source Adapter API

Логический интерфейс:

```text
SourceAdapter
```

Обязательные методы:

```text
capabilities()
inspect()
read()
write()
validate()
create()
sync_pull()
sync_push()
convert()
```

### Пример capabilities

```json
{
  "format": "xml",
  "capabilities": {
    "read": true,
    "write": true,
    "create": true,
    "validate": true,
    "incrementalSync": true,
    "convertTo": ["edt"]
  }
}
```

---

# 12. Source API

CLI:

```bash
1c-dev source info
1c-dev source detect
1c-dev source validate
1c-dev source read <object>
1c-dev source write <object>
1c-dev source sync pull
1c-dev source sync push
1c-dev source convert --to=edt
```

MCP:

```text
source.info
source.search
source.read
source.write
source.sync
source.convert
```

---

# 13. Source Sync

Определения:

```text
pull = runtime → source
push = source → runtime
```

Команды:

```bash
1c-dev source sync pull
1c-dev source sync push
1c-dev source sync status
```

`sync status` должен возвращать:

```json
{
  "status": "dirty",
  "source": "modified",
  "runtime": "unchanged",
  "changes": 3
}
```

---

# 14. Project API

CLI:

```bash
1c-dev project init
1c-dev project info
1c-dev project validate
1c-dev project detect
```

MCP:

```text
project.get
project.init
project.validate
```

---

# 15. Project Bootstrap

Должно быть возможно создать проект с нуля:

```bash
1c-dev init --type configuration
1c-dev init --type extension
1c-dev init --type external-report
1c-dev init --type external-data-processor
```

После init проект должен быть пригоден для:

```bash
1c-dev doctor
1c-dev build
1c-dev check
1c-dev test
```

без ручного открытия Конфигуратора.

---

# 16. Metadata API

Metadata API является логическим слоем и не должен заставлять клиента знать XML/EDT representation.

Операции:

```text
metadata.list
metadata.get
metadata.find
metadata.create
metadata.update
metadata.delete
metadata.references
metadata.dependencies
metadata.impact
```

CLI:

```bash
1c-dev metadata list
1c-dev metadata get Catalog.Products
1c-dev metadata find "Номенклатура"
1c-dev metadata references Catalog.Products
1c-dev metadata impact Catalog.Products.Article
```

---

# 17. Metadata Model

Пример:

```json
{
  "type": "Catalog",
  "name": "Products",
  "synonym": "Товары",
  "attributes": [
    {
      "name": "Article",
      "synonym": "Артикул",
      "type": "String",
      "length": 50
    }
  ]
}
```

Модель должна быть независимой от source format.

---

# 18. Metadata Graph

Runtime должен иметь возможность строить граф:

```text
Configuration
 ├── Catalog.Products
 │    ├── Attribute.Article
 │    └── Attribute.Price
 │
 ├── Document.Sales
 │    ├── Attribute.Counterparty
 │    └── TabularSection.Products
 │
 └── CommonModule.SalesServer
      ├── Procedure.CreateSales
      └── Procedure.CalculateTotal
```

Граф используется для:

- references;
- dependencies;
- impact analysis;
- semantic diff;
- agent context.

На MVP допускается lazy/index-on-demand построение.

---

# 19. BSL Integration

Не реализовывать собственный parser.

Интегрировать:

- BSL Language Server;
- BSL Parser.

API:

```text
bsl.analyze
bsl.symbols
bsl.definition
bsl.references
bsl.callHierarchy
bsl.hover
bsl.format
bsl.parse
```

LSP должен оставаться отдельным стандартным интерфейсом.

---

# 20. Documentation API

Использовать локальную справку установленной платформы.

Предпочтительный pipeline:

```text
Installed 1C Platform
        ↓
HBK/help extraction
        ↓
bsl-context / compatible parser
        ↓
local index
        ↓
Documentation API
```

API:

```text
docs.search
docs.get
docs.related
docs.version
```

Пример:

```bash
1c-dev docs search "ПолучитьФорму"
1c-dev docs get "Запрос.Выполнить"
```

---

# 21. Documentation Versioning

Индекс должен быть привязан к версии платформы:

```text
docs/
  8.3.25/
  8.3.26/
  8.3.27/
```

Project:

```yaml
platform:
  version: "8.3.27"
```

должен автоматически выбирать соответствующую документацию.

---

# 22. Build API

CLI:

```bash
1c-dev build
1c-dev build --artifact cf
```

Build должен:

1. определить source adapter;
2. проверить capabilities;
3. подготовить runtime;
4. синхронизировать source;
5. выполнить platform build;
6. сохранить artifact;
7. вернуть structured diagnostics.

---

# 23. Build Result

Пример:

```json
{
  "status": "failed",
  "duration": 12.3,
  "diagnostics": [
    {
      "severity": "error",
      "object": "CommonModule.SalesServer",
      "module": "Module",
      "line": 42,
      "column": 10,
      "message": "..."
    }
  ]
}
```

---

# 24. Check API

Разделить:

```text
check.static
check.platform
check.all
```

`check.static`:

- BSL Language Server;
- static analyzers.

`check.platform`:

- реальная проверка платформой.

`check.all`:

```text
static → platform
```

---

# 25. Test API

Unified API:

```text
test.discover
test.list
test.run
test.runOne
test.report
```

CLI:

```bash
1c-dev test
1c-dev test list
1c-dev test run
1c-dev test run <test>
```

Backend adapters:

```text
YAxUnit
Vanessa
```

---

# 26. Test Result

Пример:

```json
{
  "status": "failed",
  "passed": 128,
  "failed": 2,
  "skipped": 1,
  "tests": [
    {
      "name": "Sales.CalculateTotal",
      "status": "passed"
    }
  ]
}
```

---

# 27. Runtime API

Runtime — отдельная сущность от build.

API:

```text
runtime.create
runtime.start
runtime.stop
runtime.reset
runtime.update
runtime.status
runtime.execute
```

CLI:

```bash
1c-dev runtime create
1c-dev runtime start
1c-dev runtime stop
1c-dev runtime status
```

Runtime может быть:

```text
file
server
remote
container
```

Первый MVP:

```text
file
```

---

# 28. Debug API

Debugger должен использовать DAP.

Архитектура:

```text
Agent / IDE
      │
     DAP
      │
bsl-debug-server
      │
1C runtime
```

Основные операции:

```text
debug.start
debug.attach
debug.stop
debug.breakpoint
debug.continue
debug.stepOver
debug.stepInto
debug.stepOut
debug.stack
debug.variables
debug.evaluate
debug.state
```

DAP остаётся стандартным protocol-level interface.

---

# 29. Semantic Diff

Сделать отдельный сервис:

```text
diff
```

Он должен сравнивать логическую модель проекта, а не только текст.

Пример:

```text
Configuration changes

+ Catalog.Products
    + Attribute Article
        Type: String(50)

~ Document.Sales
    + TabularSection Products

~ CommonModule.SalesServer
    + Procedure CalculateTotal()
```

CLI:

```bash
1c-dev diff
1c-dev diff --semantic
```

---

# 30. Impact Analysis

API:

```text
impact.analyze
```

Пример:

```bash
1c-dev impact Catalog.Products.Article
```

Результат:

```text
Direct references:
  Document.Sales.Products.Article

Indirect references:
  CommonModule.SalesServer.CalculateTotal
  Report.SalesAnalysis

Tests:
  tests/Sales/CalculateTotal
```

---

# 31. Verify

Единая quality gate:

```bash
1c-dev verify
```

Pipeline:

```text
project validation
        ↓
source validation
        ↓
BSL analysis
        ↓
platform check
        ↓
build
        ↓
tests
        ↓
semantic diff
```

Результат:

```json
{
  "status": "failed",
  "checks": {
    "source": "passed",
    "bsl": "passed",
    "platform": "passed",
    "build": "passed",
    "unit": "failed",
    "bdd": "skipped"
  }
}
```

---

# 32. MCP

Единый MCP server:

```bash
1c-dev mcp
```

Транспорт:

- stdio;
- Streamable HTTP.

Группы tools:

### Project

```text
project.get
project.init
project.validate
```

### Source

```text
source.info
source.search
source.read
source.write
source.sync
source.convert
```

### Metadata

```text
metadata.list
metadata.get
metadata.find
metadata.create
metadata.update
metadata.references
metadata.dependencies
metadata.impact
```

### BSL

```text
bsl.analyze
bsl.symbols
bsl.definition
bsl.references
bsl.callHierarchy
```

### Docs

```text
docs.search
docs.get
docs.related
```

### Build/check

```text
build
check
```

### Tests

```text
test.list
test.run
```

### Runtime

```text
runtime.status
runtime.start
runtime.stop
runtime.execute
```

### Debug

```text
debug.start
debug.stop
debug.state
debug.evaluate
```

### Diff/impact

```text
diff
impact.analyze
```

---

# 33. Shell Escape Hatch

Допускается:

```text
shell.exec
```

но это не должно быть основным способом работы агента.

Agent должен предпочитать:

```text
metadata.create
source.write
build
test
runtime.start
```

вместо:

```text
shell.exec("some-1c-command ...")
```

---

# 34. Machine-readable CLI

Каждая команда должна поддерживать:

```bash
--output json
```

Пример:

```bash
1c-dev metadata get Catalog.Products --output json
```

Для человека:

```bash
1c-dev metadata get Catalog.Products
```

---

# 35. Exit Codes

Стандарт:

```text
0 = success
1 = validation/check failure
2 = project/configuration error
3 = required tool/environment unavailable
4 = runtime failure
5 = test failure
6 = build failure
7 = cancelled
```

---

# 36. Diagnostics Model

Все подсистемы должны приводить ошибки к единой модели.

Минимальные поля:

```json
{
  "severity": "error",
  "code": "1CXXXX",
  "message": "...",
  "file": "src/...",
  "object": "CommonModule.SalesServer",
  "module": "Module",
  "line": 42,
  "column": 10,
  "source": "platform"
}
```

Дополнительные поля:

```text
documentationLink
relatedObject
suggestion
fix
```

---

# 37. `doctor`

Команда:

```bash
1c-dev doctor
```

Проверяет:

- установленную платформу;
- версию;
- `ibcmd`;
- `1cv8`;
- EDT CLI;
- BSL Language Server;
- docs parser/index;
- test runners;
- debugger;
- Java/Node/OneScript и другие зависимости, если они нужны конкретным adapters.

Пример:

```text
1C Dev Runtime

Platform:
  8.3.27 ✓

ibcmd:
  found ✓

1C:EDT CLI:
  found ✓

BSL Language Server:
  found ✓

Documentation:
  8.3.27 indexed ✓

YAxUnit:
  found ✓

Vanessa:
  found ✓

Debugger:
  bsl-debug-server ✓
```

Также:

```bash
1c-dev doctor --output json
```

---

# 38. Toolchain Lock

Для воспроизводимости предусмотреть:

```text
1c-dev.lock
```

Он может фиксировать:

```text
platform
BSL LS
test runners
debugger
other adapters
```

Реализация lockfile может быть отложена после MVP.

---

# 39. Plugin / Adapter Discovery

Runtime должен уметь:

```bash
1c-dev adapters list
```

Пример:

```text
Source:
  xml ✓
  edt ✓

Test:
  yaxunit ✓
  vanessa ✓

Platform:
  ibcmd ✓
  1cv8 ✓
  edtcli ✓

Debug:
  dap ✓
```

Новые adapters не должны требовать изменения core.

---

# 40. Environment Model

Runtime должен поддерживать автоматическое обнаружение:

```text
platform installations
ibcmd
1cv8
1cedtcli
Java
Node
OneScript
test runners
debugger
```

При конфликте нескольких версий выбор определяется:

1. project manifest;
2. lockfile;
3. explicit CLI configuration;
4. environment discovery.

---

# 41. Security

Runtime запускает внешние процессы и поэтому должен учитывать:

- рабочий каталог;
- environment variables;
- credentials;
- file access;
- remote runtime;
- arbitrary shell execution.

`--allow-shell` / аналогичный механизм может использоваться для явного разрешения опасного escape hatch.

Credentials не должны попадать в:

- Git;
- logs;
- MCP results;
- diagnostics;
- agent context.

---

# 42. Git Integration

Git не должен быть обязательной частью runtime API, но должен поддерживаться как естественный workflow.

Рекомендуемые операции:

```bash
git status
git diff
git log
```

Дополнительный semantic diff:

```bash
1c-dev diff
```

Необходимо избегать изменения generated/build/runtime files в Git.

---

# 43. Generated Files

Проект должен иметь понятное разделение:

```text
src/
tests/
docs/
build/
.runtime/
.cache/
```

По умолчанию:

```text
build/
.runtime/
.cache/
```

не являются source.

---

# 44. Agent Rules

В корне проекта:

```text
AGENTS.md
```

Runtime может поставлять стандартный template.

Минимальные правила:

```text
# 1C Development Rules

1. Never modify generated artifacts.
2. Respect the configured source format.
3. Never manually export configuration through Designer.
4. Use metadata tools for metadata operations.
5. Do not invent platform APIs.
6. Use documentation tools for unfamiliar platform APIs.
7. Run static checks after relevant changes.
8. Build and run relevant tests before declaring a task complete.
9. Prefer debugger for reproducible runtime failures.
10. Review semantic diff before completion.
```

---

# 45. Agent Skills

Предусмотреть стандартный набор reusable skills:

```text
skills/
├── 1c-development/
├── 1c-metadata/
├── 1c-bsl/
├── 1c-testing/
├── 1c-debugging/
├── 1c-project-init/
└── 1c-platform-docs/
```

Skill должен описывать:

- когда применять;
- какие tools использовать;
- expected workflow;
- definition of done;
- типичные ошибки.

Skills не должны зависеть от конкретного агента.

---

# 46. Typical Development Workflow

## Feature

```text
project.get
      ↓
metadata.find
      ↓
docs.search
      ↓
metadata.references
      ↓
source.read
      ↓
source.write
      ↓
bsl.analyze
      ↓
build
      ↓
test
      ↓
diff
      ↓
verify
```

## Bug

```text
reproduce
    ↓
runtime.start
    ↓
debug.start
    ↓
breakpoint
    ↓
variables/evaluate
    ↓
source.write
    ↓
check
    ↓
test
    ↓
verify
```

---

# 47. Example: создание конфигурации

User:

> Создай небольшую конфигурацию магазина.

Agent:

```text
project.init(type=configuration)
```

↓

```text
metadata.create(Catalog.Products)
```

↓

```text
metadata.create(Catalog.Customers)
```

↓

```text
metadata.create(Document.Sales)
```

↓

```text
source.write(...)
```

↓

```text
build
```

↓

```text
check
```

↓

```text
test
```

В идеале никакого ручного Configurator workflow.

---

# 48. Example: создание расширения

User:

> Создай расширение, добавляющее реквизит Скидка в документ РеализацияТоваров.

Agent:

```text
project.get
metadata.find(Document.RealizationGoods)
docs.search(...)
metadata.create(extension)
source.write(...)
check
build
test
diff
verify
```

---

# 49. Source Format Switching

Проект:

```yaml
source:
  format: edt
```

Команда:

```bash
1c-dev source convert --to=xml
```

После conversion:

```yaml
source:
  format: xml
```

При этом:

- logical project model остаётся прежним;
- metadata semantics остаются прежними;
- agent workflow не меняется;
- tests остаются независимыми от source format.

---

# 50. Source Adapter Contract Tests

Каждый Source Adapter должен проходить общий набор contract tests:

```text
detect
inspect
read
write
validate
create
sync
convert
```

Для каждого adapter должна существовать capability matrix.

Пример:

| Capability | XML | EDT |
|---|---:|---:|
| read | ✓ | ✓ |
| write | ✓ | ✓ |
| create | ✓ | ✓ |
| validate | ✓ | ✓ |
| sync | ✓ | ✓ |
| convert | ✓ | ✓ |
| incremental sync | TBD | TBD |

---

# 51. Platform Adapter Contract Tests

Аналогично:

```text
create database
update database
build
check
export
import
run
stop
```

Каждый adapter обязан явно сообщать capabilities.

---

# 52. Error Handling

Ошибки внешних инструментов не должны просто прокидываться как raw stdout.

Runtime обязан:

1. сохранить raw output для debugging;
2. распарсить известные ошибки;
3. привести их к Diagnostics Model;
4. вернуть exit code;
5. предоставить agent-friendly summary.

---

# 53. Logging

Уровни:

```text
error
warn
info
debug
trace
```

По умолчанию агент получает concise structured output.

Raw logs доступны отдельно:

```bash
1c-dev logs
```

или через artifact/log reference.

---

# 54. Caching

Кандидаты:

- documentation index;
- BSL analysis;
- metadata graph;
- source parsing;
- platform discovery.

Cache должен быть:

- локальным;
- version-aware;
- invalidatable;
- не попадать в Git.

---

# 55. Performance Requirements

Для локального проекта среднего размера:

- `project.info`: < 1 сек;
- `metadata.find`: < 1 сек после индексации;
- `docs.search`: < 500 мс после индексации;
- `source.search`: < 1 сек;
- incremental BSL analysis: максимально близко к LSP latency;
- runtime operations должны не создавать ИБ заново без необходимости.

Точные benchmarks определить после MVP.

---

# 56. Compatibility Requirements

MVP должен работать минимум с:

- Windows;
- Linux, если конкретная версия платформы 1С и toolchain это позволяют.

macOS рассматривается как client/remote development environment.

Runtime не должен предполагать наличие GUI.

---

# 57. CI/CD

В CI должен быть возможен полностью headless workflow:

```bash
1c-dev doctor
1c-dev check
1c-dev build
1c-dev test
1c-dev verify
```

Никакого интерактивного UI.

---

# 58. Remote Runtime

После MVP предусмотреть:

```text
Agent machine
     │
     │ MCP/HTTP
     ▼
1C Dev Runtime
     │
     ▼
Windows/Linux host with 1C Platform
```

Это позволит использовать агент на macOS/Linux, даже если platform runtime находится на отдельной машине.

---

# 59. Observability

Runtime должен предоставлять:

```text
execution id
start time
duration
adapter
tool version
command
status
diagnostics
artifacts
logs
```

Это особенно важно для agent debugging.

---

# 60. Architecture Decision Records

Каждое важное архитектурное решение должно фиксироваться в:

```text
docs/adr/
```

Минимальный набор ADR:

```text
ADR-001 Agent independence
ADR-002 Source adapter architecture
ADR-003 Project manifest
ADR-004 XML adapter
ADR-005 EDT adapter
ADR-006 Metadata model
ADR-007 MCP architecture
ADR-008 DAP integration
ADR-009 Documentation indexing
ADR-010 Semantic diff
```

---

# 61. Repository Layout

Предлагаемый monorepo:

```text
1c-dev-runtime/
├── cli/
├── core/
├── adapters/
│   ├── source-xml/
│   ├── source-edt/
│   ├── platform-ibcmd/
│   ├── platform-1cv8/
│   ├── platform-edtcli/
│   ├── test-yaxunit/
│   ├── test-vanessa/
│   └── debug-dap/
├── services/
│   ├── metadata/
│   ├── docs/
│   ├── diff/
│   └── impact/
├── mcp/
├── schemas/
├── skills/
├── templates/
│   ├── configuration/
│   ├── extension/
│   ├── external-report/
│   └── external-data-processor/
├── tests/
├── benchmarks/
└── docs/
    ├── specification/
    └── adr/
```

Язык реализации core/CLI может быть выбран на этапе Architecture Decision.

Критерии:

- хороший subprocess/process management;
- cross-platform;
- простой distribution;
- удобный JSON;
- возможность plugin/adapter architecture;
- минимальное количество runtime dependencies.

---

# 62. MVP Scope

## MVP-0

Обязательно:

- [ ] `1c.project.yaml`;
- [ ] CLI;
- [ ] `doctor`;
- [ ] project detection;
- [ ] Source Adapter API;
- [ ] XML adapter;
- [ ] EDT adapter;
- [ ] `ibcmd` adapter;
- [ ] `1cedtcli` adapter;
- [ ] build;
- [ ] check;
- [ ] BSL LS integration;
- [ ] local documentation index;
- [ ] docs search;
- [ ] MCP.

## MVP-1

- [ ] metadata API;
- [ ] metadata graph;
- [ ] project bootstrap;
- [ ] extension bootstrap;
- [ ] EPF/ERF bootstrap;
- [ ] YAxUnit;
- [ ] Vanessa;
- [ ] runtime lifecycle.

## MVP-2

- [ ] DAP debugger;
- [ ] semantic diff;
- [ ] impact analysis;
- [ ] unified verify;
- [ ] agent skills.

## MVP-3

- [ ] remote runtime;
- [ ] Docker;
- [ ] lockfile;
- [ ] plugin marketplace/distribution;
- [ ] additional source formats;
- [ ] benchmark suite.

---

# 63. Что НЕ делать в MVP

Не разрабатывать:

- новый BSL parser;
- новый LSP;
- новый test framework;
- новую IDE;
- новый debugger;
- собственный source format;
- vector database как обязательный компонент;
- сложную distributed architecture;
- plugin marketplace.

---

# 64. Existing Ecosystem to Reuse

Проект должен исследовать и интегрировать следующие существующие компоненты:

### BSL Language Server

https://github.com/1c-syntax/bsl-language-server

Используется для LSP/diagnostics/semantic analysis и потенциально MCP.

### BSL Parser

https://github.com/1c-syntax/bsl-parser

Используется для AST/analysis, где LSP недостаточно.

### MDClasses

https://github.com/1c-syntax/mdclasses

Используется для metadata processing.

### bsl-context

https://github.com/1c-syntax/bsl-context

Используется для индексации документации платформы.

### 1CFilesConverter

https://github.com/arkuznetsov/1CFilesConverter

Используется как reference/возможный backend для source conversion.

### 1C Platform Tools

https://github.com/yellow-hammer/vscode-1c-platform-tools

Используется как reference implementation developer workflow.

### bsl-debug-server

https://github.com/yukon39/bsl-debug-server

Используется как DAP backend.

### Vanessa Runner

https://github.com/vanessa-opensource/vanessa-runner

Используется как test/automation backend.

### YAxUnit

https://github.com/bia-technologies/yaxunit

Используется как unit-test backend.

---

# 65. Критерии успеха

Проект считается успешным для MVP, если разработчик может:

### Scenario A — существующая XML конфигурация

```text
clone Git repository
↓
1c-dev doctor
↓
1c-dev build
↓
1c-dev check
↓
1c-dev test
↓
AI agent changes source
↓
1c-dev verify
```

без ручной выгрузки XML и без открытия Конфигуратора.

### Scenario B — EDT project

Тот же workflow должен работать без изменения agent-level API.

### Scenario C — новый проект

```bash
1c-dev init --type configuration
```

после чего AI agent может создать простую конфигурацию.

### Scenario D — extension

AI agent может создать extension, изменить metadata и собрать его.

### Scenario E — runtime bug

AI agent может:

```text
start runtime
→ reproduce
→ breakpoint
→ inspect
→ edit
→ test
→ verify
```

без ручной отладки через GUI.

---

# 66. Definition of Done для MVP

MVP считается готовым, если:

- два source formats работают через единый Source API;
- один и тот же MCP API работает для обоих formats;
- project manifest описывает format/platform/runtime;
- configuration можно собрать headlessly;
- static checks работают;
- documentation search работает локально;
- agent может создать проект с нуля;
- результаты build/check/test структурированы;
- `doctor` способен диагностировать environment;
- workflow не требует ручной выгрузки конфигурации;
- core не зависит от конкретной IDE;
- core не зависит от конкретного AI agent.

---

# 67. Acceptance Test

Следующий сценарий должен быть автоматизирован:

```text
1. Создать временный проект.
2. Инициализировать configuration.
3. Создать Catalog.Products.
4. Добавить Article String(50).
5. Создать CommonModule.
6. Написать BSL procedure.
7. Выполнить static check.
8. Выполнить platform check.
9. Собрать проект.
10. Запустить unit test.
11. Получить semantic diff.
12. Запросить metadata.references.
13. Запросить docs.search.
14. Переключить source format XML → EDT.
15. Повторить build/check/test.
16. Убедиться, что semantic model эквивалентен.
```

---

# 68. Основные риски

## R1. Ограничения 1cedtcli

Может оказаться, что часть операций невозможно выполнять headlessly или стабильно.

**Mitigation:** capability model + fallback на `1cv8`/`ibcmd`.

## R2. Различия XML и EDT

Не все semantics могут конвертироваться идеально.

**Mitigation:** contract tests + loss report при conversion.

## R3. Версионные различия платформы

**Mitigation:** platform version в manifest + toolchain detection.

## R4. Нестабильность энтузиастских инструментов

**Mitigation:** adapter isolation + pinned versions + health checks.

## R5. Слишком большой scope

**Mitigation:** не реализовывать parser/LSP/debugger/test framework самостоятельно.

## R6. Слишком много MCP tools

**Mitigation:** semantic grouping + minimal tool surface.

## R7. AI начинает использовать shell вместо semantic tools

**Mitigation:** AGENTS.md + MCP tool descriptions + explicit shell escape hatch.

---

# 69. Открытые архитектурные вопросы

До начала полноценной реализации необходимо принять ADR по следующим вопросам:

1. Язык реализации core/CLI.
2. Точная schema `1c.project.yaml`.
3. XML source backend: `ibcmd`, `1cv8`, `1CFilesConverter` или комбинация.
4. EDT source backend: возможности `1cedtcli`.
5. Точная модель metadata IR.
6. Способ построения metadata graph.
7. Формат semantic diff.
8. Механизм adapter discovery.
9. Plugin packaging.
10. Runtime isolation.
11. Remote runtime protocol.
12. Authentication для remote runtime.
13. Версионирование toolchain.
14. Стратегия миграции XML ↔ EDT.
15. Как обрабатывать conversion loss.
16. Насколько MCP BSL LS следует использовать отдельно от unified MCP.

---

# 70. Рекомендуемый порядок реализации

```text
Phase 0
Architecture decisions
        ↓
Phase 1
Project manifest + doctor
        ↓
Phase 2
Source Adapter API
        ↓
Phase 3
XML + EDT
        ↓
Phase 4
Platform adapters
        ↓
Phase 5
Build + Check
        ↓
Phase 6
BSL + Docs
        ↓
Phase 7
MCP
        ↓
Phase 8
Metadata
        ↓
Phase 9
Tests
        ↓
Phase 10
Runtime + Debug
        ↓
Phase 11
Semantic Diff + Impact
```

---

# 71. Рекомендация по первому спринту

Первый спринт не должен решать весь проект.

Цель:

> Доказать, что агент может работать с двумя разными source formats через единый API.

Deliverables:

```text
1c-dev project init
1c-dev doctor
1c-dev source info
1c-dev source validate
1c-dev build
1c-dev check
```

и:

```text
XmlSourceAdapter
EdtSourceAdapter
IbcmdPlatformAdapter
EdtCliPlatformAdapter
```

Плюс минимальный MCP:

```text
project.get
source.info
build
check
```

Если это работает одинаково для XML и EDT — архитектура подтверждена.

---

# 72. Стратегическая цель

После реализации runtime разработчик должен воспринимать 1С примерно так же, как современный разработчик воспринимает обычный source-controlled software project:

```text
Git
 ↓
source
 ↓
AI agent
 ↓
LSP
 ↓
build
 ↓
test
 ↓
debug
 ↓
commit
```

а не:

```text
Конфигуратор
 ↓
выгрузка
 ↓
XML
 ↓
ручные команды
 ↓
загрузка
 ↓
тестирование
 ↓
Конфигуратор
```

---

# 73. Итоговое архитектурное решение

**`1C Dev Runtime` должен быть фасадом над существующей 1С developer ecosystem, а не заменой этой ecosystem.**

Его главная ценность:

```text
             Existing tools
                  │
        ┌─────────┼─────────┐
        ▼         ▼         ▼
       LSP       DAP       CLI
        │         │         │
        └─────────┼─────────┘
                  ▼
          1C Dev Runtime
                  │
        ┌─────────┼─────────┐
        ▼         ▼         ▼
      Agent      IDE       CI
```

Ключевой контракт:

```text
Agent
  ↓
MCP / LSP / DAP / CLI
  ↓
1C Dev Runtime API
  ↓
Adapters
  ↓
1C ecosystem
```

При этом:

```text
Agent ≠ Runtime
IDE ≠ Runtime
Source Format ≠ Project Model
Source ≠ Artifact
LSP ≠ MCP
MCP ≠ DAP
```

Именно эти разделения должны считаться архитектурными инвариантами проекта.
