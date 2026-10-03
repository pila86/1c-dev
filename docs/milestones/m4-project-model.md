# M4: Project home, multi-config, templates, publish

**Статус:** In progress — контракт зафиксирован (ADR 022–026); уточнение API конфигураций [#100](https://github.com/pila86/1c-dev/issues/100); реализация [#84](https://github.com/pila86/1c-dev/issues/84)–[#96](https://github.com/pila86/1c-dev/issues/96), [GitHub milestone M4](https://github.com/pila86/1c-dev/milestone/4)

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
| Init vs configuration | `project.init` = только scope/home (манифест, без XML conf); lifecycle conf — `configuration.add|list|import|…`; empty `configurations[]`/`runtimes[]` допустимы до первого add/import | [#100](https://github.com/pila86/1c-dev/issues/100) / [ADR-027](../adr/027-configuration-lifecycle.md) / [ADR-028](../adr/028-configuration-import.md) |
| Platform templates | Discovery tmplts / `1cestart.cfg`; parse `*.mft`; `templates.*` + `configuration.import --from-template` | [024](../adr/024-platform-templates.md) |
| Publish | Фасад `publish.*`; MVP `ibsrv`; Apache/`webinst` вторым адаптером | [025](../adr/025-publish-backends.md) |
| Runtimes | Массив `runtimes[]`: `{id, configuration, type, path, default?}`; ≥1 IB на configuration (когда conf есть); один global `default` | [026](../adr/026-runtimes-array.md) |
| Schema | Манифест schema `"2"`; empty arrays на empty scope (#100) | [`1c.project.schema.v2.json`](../../schemas/1c.project.schema.v2.json) |
| Compat | Только `.1c-dev/project.yaml`; корневой `1c.project.yaml` → ошибка `1CP016`; migrate — **cancelled** (#93) | ADR-022 |
| IDE root | `ide configure --ide-root` отдельно от scope root (monorepo / оркестратор) | ADR-022 / ADR-016 |
| Drafts вне roadmap | EDT — `draft-*`; Tests → [M5](m5-tests.md) | [roadmap](../roadmap.md) |

## Целевая модель

```text
scope-root/                    # git root ИЛИ nested (products/shop)
├── src/cf/                    # после configuration.add (не после пустого init)
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
  default: local-webinst
  profiles:
    local-webinst:
      backend: webinst
      port: 8315
      runtime: main-dev
    local-ibsrv:
      backend: ibsrv
      port: 8314
      runtime: main-dev
      config: .1c-dev/publish/ibsrv.yaml
```

JSON Schema: [`schemas/1c.project.schema.v2.json`](../../schemas/1c.project.schema.v2.json) (подключён в `core/project/validate.py`, #85).

## Scope

Пять треков (+ уточнение API конфигураций). EDT / DAP / Remote — **не** входят ([draft-source-formats](draft-source-formats.md)). Test runner API — [M5](m5-tests.md) (модель test-extension в манифесте — да).

### A. Project home и schema 2

- Detect: вверх искать только `.1c-dev/project.yaml`; корневой `1c.project.yaml` — ошибка `1CP016` (без migrate).
- `project.list`: сканирование вниз от path (ограниченная глубина) для monorepo.
- **`project.init`:** только layout schema `"2"` (home + манифест + opt AGENTS/IDE); **без** scaffold XML configuration ([#100](https://github.com/pila86/1c-dev/issues/100)). Empty scope: `configurations: []`, `runtimes: []` — schema/validate OK.
- Import пишут schema `"2"`; при необходимости создают/обновляют configuration + runtime через тот же путь, что `configuration.add`, либо явно документированный import-path.
- Validate: если conf есть — ≥1 runtime на каждую; ровно один global `default: true` в `runtimes[]` (когда runtimes непусты).
- Default path ИБ при `configuration.add`: `.1c-dev/runtime/<config-id>`.
- Clean: выбранный runtime path или всё под `.1c-dev/runtime` (+ opt wipe source).
- MCP: аргумент `path` = scope root; **`project.get`** — summary состава (configurations, extensions ids, runtimes, defaults) + opt полный манифест.
- `ide configure --project` (scope) и `--ide-root` (куда писать `.cursor`); AGENTS в scope — opt-in / `none` в multi-tool.
- Should DX: `project.init --config <name>` ≡ init + `configuration.add`.

### B. Multi-config и extensions

- **`configuration.*` (CLI/MCP, #100 / ADR-028):**
  - **Must:** `add` (scaffold XML + манифест + связанный runtime), `list`, `import` (`.cf` → XML; register conf/runtime без empty scaffold);
  - **Should:** `get`, `remove` (`--yes`), `set-default`.
  - Сигнатура add: `--id`, `--name`, `--path` (default `src/<id>`), `--set-default`, `--with-runtime` (default on).
  - Сигнатура import: `--from`, `--id`, `--path`, `--force`, `--break-support`, `--with-runtime`.
- `templates/extension/` + standalone `init --type extension` (или `configuration.add` с `type=extension` — уточнить в реализации #100) и `extension.add` в configuration-проект.
- Adapter ibcmd: `--extension` на import/apply/save/load/export (spike argv до freeze API).
- `build`: configuration, затем extensions в ИБ из `runtimes[]` (`--runtime` / default / `--config`); без conf — ошибка со suggestion `configuration.add`.
- MCP/CLI: `extension.list`; установка в ИБ из XML (must); из `.cfe` — should (`extension.add --from` + `build`, #95).
- Should #112: `metadata.*` с `--extension` / nested `src/cfe/` (md-reader через `CF`; MVP — свои объекты; borrow/interceptors — xml-gen `extension.*`, follow-up).
- Несколько configurations: `--config <id>`; несколько ИБ: `--runtime <id>`.
- Отдельный `runtime.add` — **не** MVP (#100); вторая ИБ на conf — should.

### C. Каталог шаблонов платформы

- Discovery: `ConfigurationTemplatesLocation` из `1cestart.cfg` + default tmplts (Linux/Windows).
- Парсер `*.mft` → list (vendor, name, version, Source `.cf`/`.dt`/`.cfu`).
- CLI/MCP: `templates.roots`, `templates.list`, `templates.get`.
- `configuration.import --from-template <id>`: только Source `.cf` → reuse import pipeline; `.dt`/`.cfu` — discovery в `templates.*`, import не поддерживается (#111 cancelled).
- Doctor capability `templates`.

### D. Publish

- Адаптеры `ibsrv` / `webinst` (тонкие subprocess).
- CLI/MCP: `publish.up|down|status|url` (имена — ADR-025).
- **Must:** `ibsrv` + file IB; профиль ссылается на `runtime: <id>`.
- **Should:** `webinst` apache24; doctor gap, не hard-fail всего CLI.
- Артефакты под `.1c-dev/publish/`.

### E. DX / acceptance (при реализации)

- AGENTS-шаблон: happy-path `init` → `configuration.add`; **не** путать вторую conf с `extension.add` / повторным `init`.
- Integration: nested scope; ≥2 configurations с ≥1 IB каждая; extension build; templates; publish skip без platform.
- Compat: корневой `1c.project.yaml` не поддерживается (`1CP016`).

## Agent workflows (целевые)

### Greenfield (пустой scope → конфигурация)

```
1. project.init(path=…)              # только .1c-dev + манифест
2. configuration.add(name="МойМагаз")  # XML + configurations[] + runtime
3. project.get(path=…)               # состав scope
4. metadata.* / build
```

Сахар (should): `project.init --config МойМагаз` ≡ шаги 1–2.

### Ещё одна configuration в том же scope

```
1. project.get(path=…)
2. configuration.add(name="МойМагаз")   # НЕ init, НЕ extension.add
3. project.get / configuration.list
```

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
2. configuration.import --from-template <id>
3. build
```

### Расширение в ИБ

```
1. extension.add / metadata в src/cfe/…   # или extension.add --from *.cfe → XML dump
   # metadata.* --extension → #112
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
- [x] `runtimes[]`: связь ИБ↔configuration; validate ≥1 IB на config (когда conf есть); один global `default` (когда runtimes непусты)
- [x] `project.init` создаёт empty scope (без XML conf); detect только `.1c-dev/project.yaml`
- [x] `configuration.add` / `list` (CLI+MCP): scaffold + манифест + runtime; вторая conf в том же scope
- [x] `configuration.import` (CLI+MCP): empty ensure + register conf/runtime; без `project.import` (ADR-028 / #105)
- [x] `project.get` — summary состава configurations / runtimes / defaults
- [ ] `configurations[]` + `extensions[]`; build в выбранную/default ИБ
- [ ] Extension scaffold; установка extension в ИБ из XML через ibcmd
- [ ] `templates.list` / `configuration.import --from-template` для `.cf` из tmplts
- [ ] `publish` через ibsrv для default (или указанного) runtime
- [ ] MCP `path` = scope root; `project.list` находит nested `.1c-dev`
- [x] `ide configure --ide-root` не требует совпадения с scope root
- [ ] Doctor: templates / ibsrv / webinst capabilities
- [ ] ADR 022–028 Accepted (при закрытии реализации); roadmap M1–M4; EDT/Tests в `draft-*`

### Should

- [x] `project.init --config <name>` (сахар) и/или `configuration.remove` / `set-default` / `get`
- [x] Publish Apache/`webinst`
- [x] Import `.cfe` в ИБ при поддержке платформы (#95)
- [x] ~~Seed ИБ из `.dt` шаблона (#111)~~ — **cancelled** (not planned)
- [x] `metadata.*` для nested/standalone extensions (`--extension`, md-reader `CF`) (#112)
- [ ] Несколько ИБ на одну configuration (dev/demo) в acceptance

## Out of scope (M4)

- EDT / `source.convert` → [draft-source-formats](draft-source-formats.md)
- YAxUnit / Vanessa test runner API → [M5](m5-tests.md) (модель test-extension в манифесте — да)
- DAP / debug, Remote / Docker / server IB как primary
- Vendor-in vanessa-runner / EPF для `.cfe` как hard dependency
- Обязательный манифест в git root
- Полный REST-`configuration.update`; обязательный `runtime.add` в MVP (#100)

## Issues

Волны: **0** spike → **1** манифест + multi-config + publish ibsrv → **1b** configuration API → **2** templates → **3** should + acceptance.

| # | Wave | Задача | Depends on |
|---|------|--------|------------|
| [#84](https://github.com/pila86/1c-dev/issues/84) | 0 | Spike: ibcmd `--extension` + ibsrv config/lifecycle (argv freeze) — [note](../spikes/084-ibcmd-extension-ibsrv.md) | — |
| [#85](https://github.com/pila86/1c-dev/issues/85) | 1 | Schema `"2"` в коде + validate configurations/runtimes/publish + ADR 022–026 → Accepted | #84 |
| [#86](https://github.com/pila86/1c-dev/issues/86) | 1 | Project home `.1c-dev`: detect, init/import, clean, `project.list`/`get`, MCP path | #85 |
| [#87](https://github.com/pila86/1c-dev/issues/87) | 1 | Resolve `--config` / `--runtime` в build/runtime/clean/metadata + defaults | #86 |
| [#88](https://github.com/pila86/1c-dev/issues/88) | 1 | Multi-config + extensions: scaffold, build в ИБ, `extension.list` | #84, #87 |
| [#89](https://github.com/pila86/1c-dev/issues/89) | 1 | Publish ibsrv: adapter, `publish.*`, doctor ibsrv, артефакты `.1c-dev/publish/` | #84, #87 |
| [#90](https://github.com/pila86/1c-dev/issues/90) | 1 | `ide configure --project` / `--ide-root` + AGENTS opt-in для multi-tool | #86 |
| [#100](https://github.com/pila86/1c-dev/issues/100) | 1b | `project.init` без conf; `configuration.add|list|…`; `project.get` summary; empty schema arrays | #86, #88 |
| [#105](https://github.com/pila86/1c-dev/issues/105) | 1b | `configuration.import` (migrate from `project.import` + empty-scope register); ADR-028 | #100 |
| [#91](https://github.com/pila86/1c-dev/issues/91) | 2 | Templates: discovery tmplts/mft, `templates.*`, doctor `templates` | #86 |
| [#92](https://github.com/pila86/1c-dev/issues/92) | 2 | `configuration.import --from-template` для `.cf` из tmplts | #91, #105 |
| [#93](https://github.com/pila86/1c-dev/issues/93) | — | **Cancelled:** `project migrate` / dual-compat не нужны | — |
| [#94](https://github.com/pila86/1c-dev/issues/94) | 3 | should: Publish Apache/`webinst` + doctor `webinst` | #89 |
| [#95](https://github.com/pila86/1c-dev/issues/95) | 3 | should: установка extension в ИБ из `.cfe` | #88 |
| [#111](https://github.com/pila86/1c-dev/issues/111) | — | **Cancelled:** seed ИБ из `.dt` шаблона (`--from-template`) | — |
| [#112](https://github.com/pila86/1c-dev/issues/112) | 3 | should: `metadata.*` для расширений (`--extension`, md-reader `CF`) | #88, #95 |
| [#96](https://github.com/pila86/1c-dev/issues/96) | 3 | Acceptance: E2E nested + multi-config + extension + templates + publish | #86–#92, #100 |

## Links

- [GitHub milestone M4](https://github.com/pila86/1c-dev/milestone/4)
- [Roadmap](../roadmap.md)
- [M3](m3-product-adopt.md)
- [draft-source-formats](draft-source-formats.md) · [M5 tests](m5-tests.md)
- ADR: [022](../adr/022-project-home.md) · [023](../adr/023-multi-config-extensions.md) · [024](../adr/024-platform-templates.md) · [025](../adr/025-publish-backends.md) · [026](../adr/026-runtimes-array.md) · [027](../adr/027-configuration-lifecycle.md) · [028](../adr/028-configuration-import.md)
- Spike argv: [084-ibcmd-extension-ibsrv](../spikes/084-ibcmd-extension-ibsrv.md)
- Schema v2: [`schemas/1c.project.schema.v2.json`](../../schemas/1c.project.schema.v2.json)
- PRD §8 Project Model, §9 Project Types
