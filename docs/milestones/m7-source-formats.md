# M7: Source formats (EDT)

**Статус:** Planned — [GitHub milestone M7](https://github.com/pila86/1c-dev/milestone/7).  
Бывший план «M4 EDT» / черновик `draft-source-formats`; M4 закрыт как [project model](m4-project-model.md).  
Write-backend выбран: [write-backend-bakeoff](../spikes/write-backend-bakeoff.md) (**Done** 2026-11 — XML=xml-gen, EDT=**D** md-sparrow `.mdo` + export).  
Волна 0: spike [#149](https://github.com/pila86/1c-dev/issues/149) — **Done** ([spike](../spikes/149-edt-source-adapter.md), fixture `tests/fixtures/edt_spike`).

**Scope must:** полный паритет с XML (**вариант B**) — read + semantic write + `build`/`check` + `source.convert` при `source.format: edt`.

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
| EDT adapter / write D | [ADR-032](../adr/032-edt-source-adapter.md) (**Proposed**) | Accepted после waves 2–5 / #159 |
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

## Acceptance criteria

- [ ] EDT Source Adapter: detect / read path совместим с Metadata API (M2)
- [ ] `metadata.create|update|delete` работают при `source.format: edt` (write path D)
- [ ] `1c-dev source convert --to=edt` и `--to=xml` меняют `source.format` и содержимое source
- [ ] После convert тот же MCP flow (`metadata.*`, `build`, `check`) без смены tool names
- [ ] MCP: `source.convert` без shell.exec
- [ ] Integration-тесты: skip с сообщением, если нет EDT CLI / md-sparrow JDK
- [ ] Contract tests Source Adapter: XML и EDT на общем наборе capabilities (PRD §50)

## Out of scope

- Import из `.cf` (уже [M3](m3-product-adopt.md))
- Project home / multi-config / templates / publish (→ [M4](m4-project-model.md))
- YAxUnit / Vanessa (→ [M5](m5-tests.md)); `#128` Vanessa — вне M7
- DAP / debug — [M6](m6-debug.md); `#143` launch.json — вне M7
- semantic diff, verify; Remote / Docker / lockfile
- `.cf` как постоянный source format в манифесте (`source.format: cf`)
- Публичный `source.write` как замена `metadata.create`

## Manual verification

```bash
# После import (M3) или на существующем XML-проекте
1c-dev source convert --to=edt --output json
1c-dev metadata list --output json
1c-dev metadata create … --output json
1c-dev build --output json
1c-dev check --output json

1c-dev source convert --to=xml --output json
```

## Issues

[GitHub milestone M7](https://github.com/pila86/1c-dev/milestone/7). Волны = порядок.

| # | Wave | Задача | Depends on | Status |
|---|------|--------|------------|--------|
| [#149](https://github.com/pila86/1c-dev/issues/149) | 0 | Spike: EDT fixture + `1cedtcli` export/import smoke | bake-off Done | Done ([spike](../spikes/149-edt-source-adapter.md)) |
| [#150](https://github.com/pila86/1c-dev/issues/150) | 1 | ADR: EDT Source Adapter + write path D | #149 | Done ([ADR-032](../adr/032-edt-source-adapter.md)) |
| [#151](https://github.com/pila86/1c-dev/issues/151) | 1 | Doctor: capability `edt` / `1cedtcli` (+ JDK md-sparrow soft) | — | OPEN |
| [#152](https://github.com/pila86/1c-dev/issues/152) | 2 | `EdtSourceAdapter`: detect / read → Metadata API | #150, #149 | OPEN |
| [#153](https://github.com/pila86/1c-dev/issues/153) | 2 | Toolchain: pin md-sparrow + wiring `apply-mutation` | #150 | OPEN |
| [#154](https://github.com/pila86/1c-dev/issues/154) | 3 | `metadata.*` create/update/delete на `source.format: edt` | #152, #153 | OPEN |
| [#155](https://github.com/pila86/1c-dev/issues/155) | 3 | `build` / `check` для EDT: export XML → ibcmd/Designer | #152, #151 | OPEN |
| [#156](https://github.com/pila86/1c-dev/issues/156) | 4 | `source.convert` XML ↔ EDT + манифест | #152, #155 | OPEN |
| [#157](https://github.com/pila86/1c-dev/issues/157) | 4 | MCP `source.convert` | #156 | OPEN |
| [#158](https://github.com/pila86/1c-dev/issues/158) | 5 | Contract tests Source Adapter (PRD §50) + skip без EDT | #156, #154 | OPEN |
| [#159](https://github.com/pila86/1c-dev/issues/159) | 5 | Acceptance: M7 EDT E2E | #154–#158 | OPEN |

## Риски (коротко)

| Риск | Митигация |
|------|-----------|
| md-sparrow дыры на TS/синонимах (bake-off S2) | Contract tests; fallback bridge только для известных gaps; фиксировать в spike |
| `1cedtcli` / workspace collision | Fresh `-data` workspace; документировать в doctor/spike |
| Wayland / GTK для `/CheckModules` | Уже известен workaround (X11); не специфичен EDT |
| Scope creep (Remote, `.cf` format, Vanessa) | Out of scope жёстко |

## Links

- [Roadmap](../roadmap.md)
- [Bake-off](../spikes/write-backend-bakeoff.md) · [protocol](../spikes/write-backend-bakeoff-protocol.md) · [EDT spike #149](../spikes/149-edt-source-adapter.md)
- [M2](m2-metadata-api.md) · [M3](m3-product-adopt.md) · [M4](m4-project-model.md) · [M6](m6-debug.md)
- [PRD §12 Source API](../../1c-dev-runtime-PRD-v0.1.md), [§13 Sync](../../1c-dev-runtime-PRD-v0.1.md), [§49 Format switching](../../1c-dev-runtime-PRD-v0.1.md), [§50 Contract tests](../../1c-dev-runtime-PRD-v0.1.md)
- [ADR-007](../adr/007-metadata-ir.md) (XML write); [ADR-032](../adr/032-edt-source-adapter.md) (EDT adapter + write D, Proposed)
