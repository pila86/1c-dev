# M7: Source formats (EDT)

**Статус:** **In progress (wave 6)** — config EDT Done ([#159](https://github.com/pila86/1c-dev/issues/159)); nested extensions EDT — [#161](https://github.com/pila86/1c-dev/issues/161)–[#164](https://github.com/pila86/1c-dev/issues/164); write honesty — [#165](https://github.com/pila86/1c-dev/issues/165) (Subsystem content), [#167](https://github.com/pila86/1c-dev/issues/167) (`registerRecords` array). [GitHub milestone M7](https://github.com/pila86/1c-dev/milestone/7); [ADR-032](../adr/032-edt-source-adapter.md) Accepted (+ additive nested).  
Бывший план «M4 EDT» / черновик `draft-source-formats`; M4 закрыт как [project model](m4-project-model.md).  
Write-backend выбран: [write-backend-bakeoff](../spikes/write-backend-bakeoff.md) (**Done** 2026-11 — XML=xml-gen, EDT=**D** md-sparrow `.mdo` + export).  
Волна 0: spike [#149](https://github.com/pila86/1c-dev/issues/149) — **Done** ([spike](../spikes/149-edt-source-adapter.md), fixture `tests/fixtures/edt_spike`).

**Scope must:** полный паритет с XML (**вариант B**) — read + semantic write + `build`/`check` + `source.convert` при `source.format: edt` (config **и** nested `extensions[]`; YAXUNIT runner — без изменений, ADR-029).

## Goal

Единый agent/CLI API для работы с конфигурацией независимо от source format (XML и EDT): Source Adapter для EDT и `source.convert` без смены agent-level API. Агент на EDT создаёт/меняет метаданные теми же `metadata.*`, что и на XML.

## Prerequisites

- M1–M6 Done (в т.ч. M2 Metadata API, M3 import `.cf` → XML, M4 project home)
- Write-backend bake-off Done ([spike](../spikes/write-backend-bakeoff.md)): XML=A (xml-gen), EDT=D (md-sparrow `apply-mutation` + `1cedtcli` export)
- Для EDT-ветки: `1cedtcli` в окружении; JDK для md-sparrow (Temurin 25+; soft gap в doctor)

## Decisions

| Тема | Решение | Примечание |
|------|---------|------------|
| Scope M7 | **Полный паритет (B)** | Не только convert/read; `metadata.create|update|delete` на EDT |
| XML semantic write | xml-gen (без смены) | [ADR-007](../adr/007-metadata-ir.md) подтверждён bake-off |
| EDT semantic write | **D:** md-sparrow native `.mdo` (`apply-mutation`) | Bridge xml-gen → `1cedtcli import` — fallback, не primary |
| Platform load | `1cedtcli export` → XML → существующий ibcmd/Designer | Платформа не читает `.mdo` |
| Agent API | Те же tool names на `xml` и `edt` | PRD §49 / §50; без `shell.exec` |
| Schema | `source.format: edt` уже в ADR-004; additive при необходимости | Major bump не нужен без breaking |
| EDT adapter / write D | [ADR-032](../adr/032-edt-source-adapter.md) (**Accepted**) | После waves 2–5 / #159 |
| Nested extensions EDT | convert `--extension` + build export + `extension add` format=edt | Wave 6 / #161–#164; mixed xml\|edt ок |
| YAXUNIT и EDT | Не трогать: `.cfe` + `ensure` | ADR-029 §7a; не `src/` / не convert |
| Публичный `source.write` | Out of scope | Не замена `metadata.create` |

## Scope

### 1. EDT adapter + write

- Source Adapter для EDT рядом с XML (detect / read)
- Semantic write через md-sparrow (`apply-mutation`)
- `build` / `check` / `metadata.*` / `docs.*` одинаково при `source.format: edt`

### 2. Convert

- `source.convert` XML ↔ EDT без смены agent-level API
- Опциональный flow после import:

```bash
1c-dev configuration import --from configuration.cf   # XML (M3 / ADR-028)
1c-dev source convert --to=edt
```

### 3. Nested extensions (wave 6)

- `source.convert --extension <id|name>` — xml↔edt только для выбранного extension (без тихого all)
- `build`: `extensions[].source.format: edt` → `1cedtcli export` → staging → ibcmd `--extension`
- `extension add` с `format=edt` (XML scaffold → convert)
- Смешанный режим: config и extensions независимо xml|edt|cfe
- YAXUNIT не конвертится и не живёт в `src/` (cache `.cfe` + `ensure`)

## Agent workflows

### Переключение формата

> Переведи проект на EDT и проверь сборку.

```
1. source.convert(to=edt)
2. build
3. check
```

### Создание объекта на EDT

> Создай справочник Goods в текущем EDT-проекте.

```
1. metadata.create(…)   # пишет .mdo через D
2. build                # export → ibcmd
3. check
```

### Test-extension на EDT

> Переведи tests в EDT и прогони юнит-тесты.

```
1. source.convert(to=edt, extension=tests)
2. build
3. test.run            # YAXUNIT через ensure (.cfe), не из src/
```

## Acceptance criteria

- [x] EDT Source Adapter: detect / read path совместим с Metadata API (M2)
- [x] `metadata.create|update|delete` работают при `source.format: edt` (write path D)
- [x] `1c-dev source convert --to=edt` и `--to=xml` меняют `source.format` и содержимое source
- [x] После convert тот же MCP flow (`metadata.*`, `build`, `check`) без смены tool names
- [x] MCP: `source.convert` без shell.exec
- [x] Integration-тесты: skip с сообщением, если нет EDT CLI / md-sparrow JDK
- [x] Contract tests Source Adapter: XML и EDT на общем наборе capabilities (PRD §50)
- [ ] Nested `extensions[].source.format: edt`: `build` export → ibcmd (#161)
- [ ] `source.convert --extension` CLI + MCP (#162)
- [ ] `extension add` с `format=edt` (#163)
- [ ] Acceptance: convert tests → build → test.run; YAXUNIT без изменений (#164)
- [ ] EDT: hard-fail состава подсистемы + suggestion с обходом ([#165](https://github.com/pila86/1c-dev/issues/165); upstream [md-sparrow#78](https://github.com/yellow-hammer/md-sparrow/issues/78))
- [x] EDT: `registerRecords` через array (не string `Prop=value`); probe 0.6.7 — silent no-op → hard-fail `1CS010` + suggestion ([#167](https://github.com/pila86/1c-dev/issues/167))

## Out of scope

- Import из `.cf` (уже [M3](m3-product-adopt.md))
- Project home / multi-config / templates / publish (→ [M4](m4-project-model.md))
- YAxUnit / Vanessa (→ [M5](m5-tests.md)); `#128` Vanessa — вне M7
- DAP / debug — [M6](m6-debug.md); `#143` launch.json — вне M7
- semantic diff, verify; Remote / Docker / lockfile
- `.cf` как постоянный source format в манифесте (`source.format: cf`)
- Публичный `source.write` как замена `metadata.create`
- YAXUNIT как EDT/XML в `project.yaml` / `src/` (остаётся cache `.cfe` + ensure)
- Автоконверт всех nested без `--extension`
- Запись состава подсистемы в `.mdo` у себя (ждём md-sparrow#78); прочие EDT write-gaps (Number, ts-attribute) — follow-up (#166)
- Тихий no-op content на EDT — **не** out of scope: честный fail → [#165](https://github.com/pila86/1c-dev/issues/165)
- String→array для `registerRecords` — **не** out of scope → [#167](https://github.com/pila86/1c-dev/issues/167)

## Manual verification

```bash
# После import (M3) или на существующем XML-проекте
1c-dev source convert --to=edt --output json
1c-dev metadata list --output json
1c-dev metadata create … --output json
1c-dev build --output json
1c-dev check --output json

1c-dev source convert --to=xml --output json

# Wave 6 — nested extension
1c-dev source convert --to=edt --extension tests --output json
1c-dev build --output json
1c-dev test run --output json
```

## Issues

[GitHub milestone M7](https://github.com/pila86/1c-dev/milestone/7). Волны = порядок.

| # | Wave | Задача | Depends on | Status |
|---|------|--------|------------|--------|
| [#149](https://github.com/pila86/1c-dev/issues/149) | 0 | Spike: EDT fixture + `1cedtcli` export/import smoke | bake-off Done | Done ([spike](../spikes/149-edt-source-adapter.md)) |
| [#150](https://github.com/pila86/1c-dev/issues/150) | 1 | ADR: EDT Source Adapter + write path D | #149 | Done ([ADR-032](../adr/032-edt-source-adapter.md)) |
| [#151](https://github.com/pila86/1c-dev/issues/151) | 1 | Doctor: capability `edt` / `1cedtcli` (+ JDK md-sparrow soft) | — | Done |
| [#152](https://github.com/pila86/1c-dev/issues/152) | 2 | `EdtSourceAdapter`: detect / read → Metadata API | #150, #149 | Done |
| [#153](https://github.com/pila86/1c-dev/issues/153) | 2 | Toolchain: pin md-sparrow + wiring `apply-mutation` | #150 | Done |
| [#154](https://github.com/pila86/1c-dev/issues/154) | 3 | `metadata.*` create/update/delete на `source.format: edt` | #152, #153 | Done |
| [#155](https://github.com/pila86/1c-dev/issues/155) | 3 | `build` / `check` для EDT: export XML → ibcmd/Designer | #152, #151 | Done |
| [#156](https://github.com/pila86/1c-dev/issues/156) | 4 | `source.convert` XML ↔ EDT + манифест | #152, #155 | Done |
| [#157](https://github.com/pila86/1c-dev/issues/157) | 4 | MCP `source.convert` | #156 | Done |
| [#158](https://github.com/pila86/1c-dev/issues/158) | 5 | Contract tests Source Adapter (PRD §50) + skip без EDT | #156, #154 | Done |
| [#159](https://github.com/pila86/1c-dev/issues/159) | 5 | Acceptance: M7 EDT E2E | #154–#158 | Done (`tests/test_m7_acceptance.py`) |
| [#161](https://github.com/pila86/1c-dev/issues/161) | 6 | `build`: nested `extensions[].source.format: edt` | #155 | Open |
| [#162](https://github.com/pila86/1c-dev/issues/162) | 6 | `source.convert --extension` XML ↔ EDT (CLI + MCP) | #156, #157 | Open |
| [#163](https://github.com/pila86/1c-dev/issues/163) | 6 | `extension add` с `format=edt` | #161, #162 | Open |
| [#164](https://github.com/pila86/1c-dev/issues/164) | 6 | Acceptance: nested extension EDT E2E (+ test.run) | #161–#163 | Open |
| [#165](https://github.com/pila86/1c-dev/issues/165) | 6 | EDT: hard-fail состава подсистемы + обход в diagnostic | #154; [md-sparrow#78](https://github.com/yellow-hammer/md-sparrow/issues/78) | Open |
| [#167](https://github.com/pila86/1c-dev/issues/167) | 6 | EDT: `registerRecords` — array wire (не string); probe + fix/fail | #154 | Done (worst: 1CS010) |

## Риски (коротко)

| Риск | Митигация |
|------|-----------|
| md-sparrow дыры на TS/синонимах (bake-off S2) | Contract tests; fallback bridge только для известных gaps; фиксировать в spike |
| md-sparrow EDT: `contentRefs` не пишется (тихий no-op) | Upstream [md-sparrow#78](https://github.com/yellow-hammer/md-sparrow/issues/78); у нас hard-fail + suggestion [#165](https://github.com/pila86/1c-dev/issues/165) |
| `registerRecords` как string в DTO (наш wire) | [#167](https://github.com/pila86/1c-dev/issues/167): coerce → array; probe md-sparrow 0.6.7 EDT — array OK, `.mdo` no-op → hard-fail `1CS010` + suggestion (ручной `.mdo` / convert XML) |
| `1cedtcli` / workspace collision | Fresh `-data` workspace; документировать в doctor/spike |
| Wayland / GTK для `/CheckModules` | Уже известен workaround (X11); не специфичен EDT |
| Scope creep (Remote, `.cf` format, Vanessa) | Out of scope жёстко |
| `1cedtcli` import/export для ConfigurationExtension | Smoke на `larek`/`tests` до большого diff; staging per-ext |
| Путаница tests vs YAXUNIT | YAXUNIT только ensure; не convert / не `extension add` в src |

## Links

- [Roadmap](../roadmap.md)
- [Bake-off](../spikes/write-backend-bakeoff.md) · [protocol](../spikes/write-backend-bakeoff-protocol.md) · [EDT spike #149](../spikes/149-edt-source-adapter.md)
- [M2](m2-metadata-api.md) · [M3](m3-product-adopt.md) · [M4](m4-project-model.md) · [M6](m6-debug.md)
- [PRD §12 Source API](../../1c-dev-runtime-PRD-v0.1.md), [§13 Sync](../../1c-dev-runtime-PRD-v0.1.md), [§49 Format switching](../../1c-dev-runtime-PRD-v0.1.md), [§50 Contract tests](../../1c-dev-runtime-PRD-v0.1.md)
- [ADR-007](../adr/007-metadata-ir.md) (XML write); [ADR-032](../adr/032-edt-source-adapter.md) (EDT adapter + write D, Accepted)
