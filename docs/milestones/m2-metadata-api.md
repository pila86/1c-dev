# M2: Metadata API (read + write expansion + delete)

## Goal

Агент читает существующую конфигурацию через Metadata API и развивает её без ручного XML: добавляет реквизиты в уже созданные объекты, создаёт типы метаданных шире, чем `Catalog` (документы, регистры и т.д.), и удаляет целые объекты по QName.

## Prerequisites

- M1 зелёный: `init` → `metadata.create(Catalog)` → `build` → `check`
- Write-backend xml-gen (ADR-007) доступен через doctor
- Контракт IR v1: [ADR-011](../adr/011-metadata-ir-v1.md)

## Scope

Три связанных трека в одном milestone: **read**, **write expansion** (IR v1 + update / новые типы) и **delete** (целые объекты).

### A. Read-only (исходный M2)

```text
metadata.list
metadata.get
metadata.find
```

- Источник — project source (XML в M2; EDT — после M3)
- Результат — Metadata IR / structured JSON, не сырой XML
- Prefer MDClasses / существующие readers (G7), не парсить XML ad hoc в core

### B. `metadata.update` — реквизиты в существующих объектах

```bash
1c-dev metadata update Catalog.Products --attr "Price:Number:15.2:Цена"
# MCP: metadata.update
```

Типичный agent flow:

```text
metadata.get(Catalog.Products)
  → metadata.update(... attributes+=[...])
  → build / check
```

- Добавление реквизитов (и синонимов/простых свойств) к уже существующему объекту
- Конфликт имён (реквизит уже есть) → structured diagnostic, source не меняется
- Без публичного `source.write`

### C. `metadata.create` — типы шире Catalog (IR v1)

Минимальный набор для agent-сценария «небольшой магазин» (PRD §47):

| Тип | Приоритет | Заметки |
|-----|-----------|---------|
| `Catalog` | уже M1 | расширить типы атрибутов при необходимости (Boolean, Date, ref); ТЧ — та же модель IR, что у Document |
| `Document` | must | реквизиты; табличные части — желательно в M2 (общая конструкция IR с Catalog) |
| `Enum` | should | простые перечисления |
| `InformationRegister` | should | измерения / ресурсы (упрощённый IR) |
| `AccumulationRegister` | should | упрощённый IR |
| `CommonModule` | stretch | модуль + флаги; тело BSL может остаться через узкий write позже |
| Charts / BusinessProcess / … | out | → later |

Qualified names: `Document.Sales`, `InformationRegister.Prices`, …

### D. `metadata.delete` — удаление целых объектов

```bash
1c-dev metadata delete Catalog.Products --output json
# MCP: metadata.delete
```

Типичный agent flow:

```text
metadata.get(Catalog.Products)
  → metadata.delete(Catalog.Products)
  → metadata.list / get
```

- Удаляет артефакты объекта из `source.path` и регистрацию в `Configuration.xml`
- Объект не найден → structured diagnostic, source не меняется
- Без cascade по ссылкам (битые `Ref` допустимы до graph / M5)
- Удаление вложенных элементов (атрибуты, ТЧ, …) — open design в issue delete, не must M2

## Agent workflows

### Добавить реквизит в существующий справочник

> Добавь в Товары реквизит Цена (число 15.2).

```
1. metadata.get(Catalog.Products)
2. metadata.update(Catalog.Products, attributes+=[Price])
3. build
4. check
```

### Документ и связанные объекты

> Создай документ Продажи с реквизитом Контрагент и ТЧ Товары.

```
1. metadata.create(Document.Sales, ...)
2. metadata.list / metadata.get
3. build
4. check
```

### Удалить объект

> Удали справочник Products.

```
1. metadata.delete(Catalog.Products)
2. metadata.list / metadata.get
```

## Acceptance criteria

### Read

- [ ] `metadata.list` возвращает объекты конфигурации (тип + имя + qname)
- [ ] `metadata.get <QName>` возвращает IR объекта (включая attributes)
- [ ] `metadata.find` ищет по имени / синониму
- [ ] MCP tools `metadata.list` / `get` / `find` без shell.exec
- [ ] Нет платформы → read всё равно работает по source (в отличие от build)

### Update

- [ ] `metadata.update` добавляет реквизит(ы) в существующий `Catalog` (и в типы из C, по мере поддержки)
- [ ] Повторное добавление того же имени → ошибка с diagnostic, source не повреждён
- [ ] После update `metadata.get` отражает изменения; `build` / `check` проходят

### Create beyond Catalog

- [ ] `metadata.create Document.*` пишет XML + регистрацию в `Configuration.xml`
- [ ] Хотя бы один регистр (`InformationRegister` или `AccumulationRegister`) через create
- [ ] `Enum` через create (should)
- [ ] Integration: create Document (+ attr) → build → check (skip без platform / xml-gen)

### Delete

- [ ] `metadata.delete <QName>` удаляет объект из source + `Configuration.xml`
- [ ] Несуществующий QName → diagnostic, source intact
- [ ] После delete `metadata.get` / `list` согласованы; MCP `metadata.delete` без shell.exec

### Общее

- [ ] IR v1 задокументирован ([ADR-011](../adr/011-metadata-ir-v1.md))
- [ ] Doctor capability отражает поддерживаемые write-типы
- [ ] CLI и MCP используют один `core.metadata` API

## Out of scope M2

- EDT / `source.convert` / import `.cf` (→ [M3](m3-source-formats.md))
- `references` / `dependencies` / `impact` (→ later / M5 graph)
- Nested delete (атрибуты / ТЧ / values / dimensions) — open design в issue delete
- Публичный `source.write` как замена Metadata API
- Полное покрытие всех видов метаданных платформы
- Расширения (`project.type: extension`) и изменение объектов базовой конфигурации через extension
- YAxUnit / docs / DAP (→ M4 / M5)

## Manual verification

```bash
# Read
1c-dev metadata list --output json
1c-dev metadata get Catalog.Products --output json

# Update
1c-dev metadata update Catalog.Products \
  --attr "Price:Number:15.2:Цена" --output json

# Create Document
1c-dev metadata create Document.Sales \
  --synonym "Продажи" --output json

# Delete
1c-dev metadata delete Catalog.Products --output json

1c-dev build --output json
1c-dev check --output json
```

## Links

- [GitHub milestone M2](https://github.com/pila86/1c-dev/milestone/2)
- [Roadmap](../roadmap.md)
- [M1](m1-catalog-via-agent.md)
- [M3](m3-source-formats.md)
- [ADR-007](../adr/007-metadata-ir.md) (IR v0 + xml-gen)
- [ADR-011](../adr/011-metadata-ir-v1.md) (IR v1)
- [PRD §16–§18](../../1c-dev-runtime-PRD-v0.1.md), [§47](../../1c-dev-runtime-PRD-v0.1.md)

## Issues

| # | Задача | Depends on |
|---|--------|------------|
| [#20](https://github.com/pila86/1c-dev/issues/20) | ADR: Metadata IR v1 | — |
| [#21](https://github.com/pila86/1c-dev/issues/21) | Reader: `metadata.list` / `get` / `find` (CLI + core) | #20 |
| [#22](https://github.com/pila86/1c-dev/issues/22) | `metadata.update` — реквизиты в существующих объектах | #20, #21 |
| [#29](https://github.com/pila86/1c-dev/issues/29) | `metadata.delete` — удаление объектов из source | #21, #22 |
| [#23](https://github.com/pila86/1c-dev/issues/23) | `metadata.create` Document (+ tabular sections) | #20 |
| [#24](https://github.com/pila86/1c-dev/issues/24) | `metadata.create` Enum / InformationRegister / AccumulationRegister | #23 |
| [#25](https://github.com/pila86/1c-dev/issues/25) | Doctor: capability поддерживаемых write-типов | #23, #24 |
| [#26](https://github.com/pila86/1c-dev/issues/26) | MCP tools: list / get / find / update / delete + expanded create | #21, #22, #23, #29 |
| [#27](https://github.com/pila86/1c-dev/issues/27) | Acceptance tests M2 | #26 |
| [#28](https://github.com/pila86/1c-dev/issues/28) | stretch: `metadata.create` CommonModule | #23 |
