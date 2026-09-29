# M4: Project home, multi-config, templates, publish

**Статус:** Planned (документация контракта; реализация кода — отдельные issues)

## Goal

Сделать `1c-dev` пригодным для multi-tool monorepo и нескольких конфигураций:

- дом toolchain = `.1c-dev/` (не захват git root);
- несколько конфигураций и расширений в одном scope;
- несколько ИБ через `runtimes[]` (связь ИБ ↔ configuration, ≥1 IB на config);
- import из каталога шаблонов платформы (tmplts), не только из `.cf`;
- установка расширений в ИБ;
- публикация ИБ (must: автономный сервер `ibsrv`; should: Apache/`webinst`).

## Prerequisites

- M1–M3 Done: init, metadata, build/check, import `.cf`, runtime client, ide configure, packaging
- Платформа 1С 8.3.x, `ibcmd` (для build/extensions)
- Для publish must: `ibsrv`; для should Apache — `webinst` + веб-сервер

## Decisions

| Тема | Решение | ADR |
|------|---------|-----|
| Project home | Каталог `.1c-dev/`; манифест `.1c-dev/project.yaml`; scope root = родитель; пути relative к scope root | [022](../adr/022-project-home.md) |
| Multi-config + extensions | `configurations[]` + `extensions[]`; CLI/MCP `--config`; build с ibcmd `--extension` | [023](../adr/023-multi-config-extensions.md) |
| Platform templates | Discovery tmplts / `1cestart.cfg`; parse `*.mft`; `templates.*` + `project.import --from-template` | [024](../adr/024-platform-templates.md) |
| Publish | Фасад `publish.*`; MVP `ibsrv`; Apache/`webinst` вторым адаптером | [025](../adr/025-publish-backends.md) |
| Runtimes | Массив `runtimes[]`: `{id, configuration, type, path, default?}`; ≥1 IB на configuration; один global `default` | [026](../adr/026-runtimes-array.md) |
| Schema | Манифест schema `"2"`; рабочий код M3 остаётся на `"1"` до реализации | эскиз [`1c.project.schema.v2.json`](../../schemas/1c.project.schema.v2.json) |
| Compat | Dual detect: `.1c-dev/project.yaml`, иначе legacy `1c.project.yaml` + warning; `project migrate` — should | ADR-022 |
| IDE root | `ide configure --ide-root` отдельно от scope root (monorepo / оркестратор) | ADR-022 / ADR-016 |
| Drafts вне roadmap | EDT / Tests не нумеруются; файлы `draft-*` | [roadmap](../roadmap.md) |

## Целевая модель

```text
scope-root/                    # git root ИЛИ nested (products/shop)
├── src/cf/
├── src/cfe/<ext-name>/
└── .1c-dev/
    ├── project.yaml           # манифест schema "2"
    ├── runtime/               # каталоги ИБ: main/, buh/, …
    └── publish/               # yaml ibsrv и state
```

### Эскиз манифеста

```yaml
schema: "2"
project:
  name: shop
platform:
  version: "8.3.27"
configurations:
  - id: main
    type: configuration
    default: true
    source: { format: xml, path: src/cf }
    extensions:
      - id: custom
        name: CustomExt
        purpose: product
        source: { format: xml, path: src/cfe/custom }
      - id: tests
        name: Tests
        purpose: tests
        source: { format: xml, path: src/cfe/tests }
  - id: buh
    type: configuration
    source: { format: xml, path: src/buh }
runtimes:
  - id: main-dev
    configuration: main
    type: file
    path: .1c-dev/runtime/main
    default: true
  - id: buh-dev
    configuration: buh
    type: file
    path: .1c-dev/runtime/buh
publish:
  default: local-ibsrv
  profiles:
    local-ibsrv:
      backend: ibsrv
      port: 8314
      runtime: main-dev
      config: .1c-dev/publish/ibsrv.yaml
```

Полный JSON Schema-эскиз: [`schemas/1c.project.schema.v2.json`](../../schemas/1c.project.schema.v2.json) (не подключён к коду до реализации M4).

## Scope

Пять треков. EDT / Test runner / DAP / Remote — **не** входят ([draft-source-formats](draft-source-formats.md), [draft-tests](draft-tests.md)).

### A. Project home и schema 2

- Detect: вверх искать `.1c-dev/project.yaml`; legacy корневой `1c.project.yaml` — warning + работа.
- `project.list`: сканирование вниз от path (ограниченная глубина) для monorepo.
- Init/import пишут только layout schema `"2"` (одна configuration + один связанный runtime по умолчанию).
- Validate: ≥1 runtime на каждую configuration; ровно один global `default: true` в `runtimes[]`.
- Default path ИБ при init: `.1c-dev/runtime/<config-id>`.
- Clean: выбранный runtime path или всё под `.1c-dev/runtime` (+ opt wipe source).
- MCP: аргумент `path` = scope root; `project.get` возвращает `home`, `root`, `manifest_path`, runtimes.
- `ide configure --project` (scope) и `--ide-root` (куда писать `.cursor`); AGENTS в scope — opt-in / `none` в multi-tool.

### B. Multi-config и extensions

- `templates/extension/` + `init --type extension` (standalone) и добавление extension в configuration-проект.
- Adapter ibcmd: `--extension` на import/apply/save/load/export (spike argv до freeze API).
- `build`: configuration, затем extensions в ИБ из `runtimes[]` (`--runtime` / default / `--config`).
- MCP/CLI: `extension.list`; установка в ИБ из XML (must); из `.cfe` — should.
- Несколько configurations: `--config <id>`; несколько ИБ: `--runtime <id>`.

### C. Каталог шаблонов платформы

- Discovery: `ConfigurationTemplatesLocation` из `1cestart.cfg` + default tmplts (Linux/Windows).
- Парсер `*.mft` → list (vendor, name, version, Source `.cf`/`.dt`/`.cfu`).
- CLI/MCP: `templates.roots`, `templates.list`, `templates.get`.
- `project.import --from-template <id>`: `.cf` → reuse import pipeline; `.dt` → seed runtime (не подмена XML source без явного флага).
- Doctor capability `templates`.

### D. Publish

- Адаптеры `ibsrv` / `webinst` (тонкие subprocess).
- CLI/MCP: `publish.up|down|status|url` (имена — ADR-025).
- **Must:** `ibsrv` + file IB; профиль ссылается на `runtime: <id>`.
- **Should:** `webinst` apache24; doctor gap, не hard-fail всего CLI.
- Артефакты под `.1c-dev/publish/`.

### E. DX / acceptance (при реализации)

- AGENTS-шаблон под `.1c-dev` + multi-tool monorepo.
- Integration: nested scope; ≥2 configurations с ≥1 IB каждая; extension build; templates; publish skip без platform.
- Compat: legacy `1c.project.yaml` детектится.

## Agent workflows (целевые)

### Nested monorepo

> Конфигурация лежит в `products/shop`, оркестратор — в корне repo.

```
1. project.list(path=<repo root>) → найти scope
2. project.get(path=products/shop)
3. build / metadata.* с path=products/shop
```

### Import из шаблона платформы

```
1. templates.list
2. project.import --from-template <id>
3. build
```

### Расширение в ИБ

```
1. metadata / правки в src/cfe/…
2. build   # conf + extensions → default runtime IB
3. runtime.start
```

### Публикация

```
1. build
2. publish.up   # ibsrv на default/указанный runtime
3. publish.url
```

## Acceptance criteria

### Must

- [ ] Layout `.1c-dev/project.yaml`; пути relative к scope root
- [ ] `runtimes[]`: связь ИБ↔configuration; validate ≥1 IB на config; один global `default`
- [ ] Init создаёт configuration + связанный runtime; dual detect + warning на legacy
- [ ] `configurations[]` + `extensions[]`; build в выбранную/default ИБ
- [ ] Extension scaffold; установка extension в ИБ из XML через ibcmd
- [ ] `templates.list` / `project.import --from-template` для `.cf` из tmplts
- [ ] `publish` через ibsrv для default (или указанного) runtime
- [ ] MCP `path` = scope root; `project.list` находит nested `.1c-dev`
- [ ] `ide configure --ide-root` не требует совпадения с scope root
- [ ] Doctor: templates / ibsrv / webinst capabilities
- [ ] ADR 022–026 Accepted (при закрытии реализации); roadmap M1–M4; EDT/Tests в `draft-*`

### Should

- [ ] `project migrate` legacy → `.1c-dev`
- [ ] Publish Apache/`webinst`
- [ ] Import `.cfe` в ИБ при поддержке платформы
- [ ] Seed ИБ из `.dt` шаблона
- [ ] Несколько ИБ на одну configuration (dev/demo) в acceptance

## Out of scope (M4)

- EDT / `source.convert` → [draft-source-formats](draft-source-formats.md)
- YAxUnit / Vanessa test runner API → [draft-tests](draft-tests.md) (модель test-extension в манифесте — да)
- DAP / debug, Remote / Docker / server IB как primary
- Vendor-in vanessa-runner / EPF для `.cfe` как hard dependency
- Обязательный манифест в git root

## Suggested work packages (реализация — вне текущего docs-цикла)

| Тема | Зависит от |
|------|------------|
| Spike ibcmd `--extension` + ibsrv config init | платформа |
| ADR 022–026 → Accepted + schema 2 в коде | spike |
| Detect/init/import/build под `.1c-dev` + `runtimes[]` | schema |
| Extensions build + scaffold | ibcmd spike |
| Templates discovery + import-from-template | ADR-015 reuse |
| Publish ibsrv (+ webinst should) | runtimes |
| Acceptance E2E nested + multi-IB | треки A–D |

## Links

- [Roadmap](../roadmap.md)
- [M3](m3-product-adopt.md)
- [draft-source-formats](draft-source-formats.md) · [draft-tests](draft-tests.md)
- ADR: [022](../adr/022-project-home.md) · [023](../adr/023-multi-config-extensions.md) · [024](../adr/024-platform-templates.md) · [025](../adr/025-publish-backends.md) · [026](../adr/026-runtimes-array.md)
- Schema v1 (код): [`schemas/1c.project.schema.json`](../../schemas/1c.project.schema.json)
- Schema v2 (эскиз): [`schemas/1c.project.schema.v2.json`](../../schemas/1c.project.schema.v2.json)
- PRD §8 Project Model, §9 Project Types
