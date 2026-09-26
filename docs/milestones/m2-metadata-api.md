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

- Источник — project source (XML в M2; EDT — после M4)
- Результат — Metadata IR / structured JSON, не сырой XML
- Prefer MDClasses / существующие readers (G7), не парсить XML ad hoc в core

### B. `metadata.update` — ops над реквизитами существующих объектов

```bash
1c-dev metadata update Catalog.Products \
  --op add-attribute --value "Price:Number(15,2)"
1c-dev metadata update Catalog.Products \
  --op modify-attribute --value "Price: synonym=Цена"
1c-dev metadata update Catalog.Products \
  --op remove-attribute --value "Price"
# сахар IR: --attr "Price:Number:15.2:Цена" → add + modify synonym
# ТЧ: --ts "Lines:Строки" / --ts-attr "Lines.Qty:Number:15.3:Кол"
# регистры: --dimension / --resource; Enum: --value Name[:Synonym]
# CommonModule: --server / set-flag → modify-property
# MCP: metadata.update (operations[])
```

Типичный agent flow:

```text
metadata.get(Catalog.Products)
  → metadata.update(ops=[add-attribute / modify-attribute / …])
  → build / check
```

- Явные ops: `add-attribute`, `modify-attribute`, `remove-attribute` (Catalog в #22; Document / ТЧ — #35; Enum values / dimensions / resources регистров — #39)
- Дубль add / modify|remove несуществующего → `ok` + `warning`, source не менялся
- Объект не найден → error diagnostic, source intact
- Без публичного `source.write`

### C. `metadata.create` — типы шире Catalog (IR v1)

Минимальный набор для agent-сценария «небольшой магазин» (PRD §47):

| Тип | Приоритет | Заметки |
|-----|-----------|---------|
| `Catalog` | уже M1 | расширить типы атрибутов при необходимости (Boolean, Date, ref); ТЧ — та же модель IR, что у Document |
| `Document` | must, **done** | реквизиты + табличные части (#23 / #35) |
| `Enum` | should, **done** | простые перечисления (#24); update values — #39 |
| `InformationRegister` | must (хотя бы один регистр), **done** | измерения / ресурсы (#24 / #39) |
| `AccumulationRegister` | should, **done** | упрощённый IR (#24 / #39) |
| `CommonModule` | stretch, **done** | create + флаги (#28); update флагов (#40); тело BSL later |
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
- Без cascade по ссылкам (битые `Ref` допустимы до graph / M6)
- Удаление атрибутов — через `metadata.update` `remove-attribute`; nested ТЧ / values / … — later, не must `metadata.delete`

## Agent workflows

### Добавить реквизит в существующий справочник

> Добавь в Товары реквизит Цена (число 15.2).

```
1. metadata.get(Catalog.Products)
2. metadata.update(Catalog.Products, ops=[add-attribute Price])
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

### Enum и регистр

> Создай перечисление СтатусыЗаказа и регистр сведений Цены.

```
1. metadata.create(Enum.OrderStatuses, ...)
2. metadata.create(InformationRegister.Prices, ...)
3. metadata.list / metadata.get
4. build
5. check
```

### Удалить объект

> Удали справочник Products.

```
1. metadata.delete(Catalog.Products)
2. metadata.list / metadata.get
```

## Acceptance criteria

Feature-issues #20–#26, #28, #29, #35, #39, #40 и сквозной acceptance [#27](https://github.com/pila86/1c-dev/issues/27) закрыты.

### Read

- [x] `metadata.list` возвращает объекты конфигурации (тип + имя + qname)
- [x] `metadata.get <QName>` возвращает IR объекта (включая attributes)
- [x] `metadata.find` ищет по имени / синониму
- [x] MCP tools `metadata.list` / `get` / `find` без shell.exec
- [x] Нет платформы → read всё равно работает по source (в отличие от build)

### Update

- [x] `metadata.update` выполняет `add-attribute` / `modify-attribute` / `remove-attribute` на существующем `Catalog` (и Document / ТЧ — #35)
- [x] `metadata.update` ops для `Enum` (values) и регистров (dimensions / resources) — #39
- [x] Повторное добавление того же имени → `ok` + warning diagnostic, source не повреждён
- [x] После успешного update `metadata.get` / поле `ir` отражают изменения (feature / integration-тесты)
- [x] stretch: `metadata.update` флаги CommonModule (`set-flag` / CLI flags) — #40

### Create beyond Catalog

- [x] `metadata.create Document.*` пишет XML + регистрацию в `Configuration.xml` (в т.ч. ТЧ)
- [x] Хотя бы один регистр (`InformationRegister` или `AccumulationRegister`) через create
- [x] `Enum` через create
- [x] stretch: `metadata.create CommonModule.*` (+ флаги) — #28

### Delete

- [x] `metadata.delete <QName>` удаляет объект из source + `Configuration.xml`
- [x] Несуществующий QName → diagnostic, source intact
- [x] После delete `metadata.get` / `list` согласованы; MCP `metadata.delete` без shell.exec

### Общее

- [x] IR v1 задокументирован ([ADR-011](../adr/011-metadata-ir-v1.md))
- [x] Doctor capability отражает поддерживаемые write-типы
- [x] CLI и MCP используют один `core.metadata` API

### Acceptance (#27)

- [x] Integration E2E: Document (+ attr + ТЧ) → update → Enum + регистр → delete → list/get → build → check (skip без platform / xml-gen / md-reader) — [#27](https://github.com/pila86/1c-dev/issues/27) (`tests/test_m2_acceptance.py`)
- [x] Запуск задокументирован: `poetry run pytest -m integration`

## Out of scope M2

- Import `.cf`, user install, `setup`, BSL LS MCP, docs/context (→ [M3](m3-product-adopt.md))
- EDT / `source.convert` (→ [M4](m4-source-formats.md))
- `references` / `dependencies` / `impact` (→ later / M6 graph)
- Nested delete ТЧ / values / dimensions через `metadata.delete` (атрибуты / ТЧ / values / dimensions / resources — через `metadata.update`; Enum/регистры — #39)
- Публичный `source.write` как замена Metadata API
- Полное покрытие всех видов метаданных платформы
- Расширения (`project.type: extension`) и изменение объектов базовой конфигурации через extension
- YAxUnit / DAP (→ M5 / M6)

## Manual verification

```bash
# Read
1c-dev metadata list --output json
1c-dev metadata get Catalog.Products --output json

# Update Catalog
1c-dev metadata update Catalog.Products \
  --op add-attribute --value "Price:Number(15,2)" --output json
1c-dev metadata update Catalog.Products \
  --attr "Discount:Number:10.2:Скидка" --output json
1c-dev metadata update Catalog.Products \
  --op remove-attribute --value "Discount" --output json

# Create Document + ТЧ
1c-dev metadata create Document.Sales \
  --synonym "Продажи" \
  --attr "Counterparty:Ref:Catalog.Counterparties:Контрагент" \
  --ts "Products:Товары" \
  --ts-attr "Products.Qty:Number:15.3:Количество" \
  --output json

# Create Enum + регистр
1c-dev metadata create Enum.OrderStatuses \
  --synonym "СтатусыЗаказа" \
  --value "New:Новый" --value "Done:Выполнен" \
  --output json
1c-dev metadata create InformationRegister.Prices \
  --synonym "Цены" \
  --dimension "Product:Ref:Catalog.Products:Товар" \
  --resource "Price:Number:15.2:Цена" \
  --output json

# Update ТЧ / измерение (примеры)
1c-dev metadata update Document.Sales \
  --ts-attr "Products.Price:Number:15.2:Цена" --output json
1c-dev metadata update InformationRegister.Prices \
  --dimension "Currency:String:10:Валюта" --output json

# Stretch: CommonModule
1c-dev metadata create CommonModule.SalesServer \
  --server --output json

# Delete
1c-dev metadata delete Catalog.Products --output json

1c-dev build --output json
1c-dev check --output json
```

## Links

- [GitHub milestone M2](https://github.com/pila86/1c-dev/milestone/2)
- [Roadmap](../roadmap.md)
- [M1](m1-catalog-via-agent.md)
- [M3](m3-product-adopt.md)
- [M4](m4-source-formats.md)
- [ADR-007](../adr/007-metadata-ir.md) (IR v0 + xml-gen)
- [ADR-011](../adr/011-metadata-ir-v1.md) (IR v1)
- [PRD §16–§18](../../1c-dev-runtime-PRD-v0.1.md), [§47](../../1c-dev-runtime-PRD-v0.1.md)

## Issues

| # | Задача | Depends on |
|---|--------|------------|
| [#20](https://github.com/pila86/1c-dev/issues/20) | ADR: Metadata IR v1 | — |
| [#21](https://github.com/pila86/1c-dev/issues/21) | Reader: `metadata.list` / `get` / `find` (CLI + core) | #20 |
| [#22](https://github.com/pila86/1c-dev/issues/22) | `metadata.update` — реквизиты в существующих объектах | #20, #21 |
| [#35](https://github.com/pila86/1c-dev/issues/35) | `metadata.update` — ops для табличных частей (Catalog / Document) | #22, #23 |
| [#39](https://github.com/pila86/1c-dev/issues/39) | `metadata.update` — ops для Enum и регистров (should) | #22, #24 |
| [#29](https://github.com/pila86/1c-dev/issues/29) | `metadata.delete` — удаление объектов из source | #21, #22 |
| [#23](https://github.com/pila86/1c-dev/issues/23) | `metadata.create` Document (+ tabular sections) | #20 |
| [#24](https://github.com/pila86/1c-dev/issues/24) | `metadata.create` Enum / InformationRegister / AccumulationRegister | #23 |
| [#25](https://github.com/pila86/1c-dev/issues/25) | Doctor: capability поддерживаемых write-типов | #23, #24 |
| [#26](https://github.com/pila86/1c-dev/issues/26) | MCP tools: list / get / find / update / delete + expanded create | #21, #22, #23, #29 |
| [#27](https://github.com/pila86/1c-dev/issues/27) | Acceptance: E2E Document+ТЧ / Enum / регистр / delete | #26 |
| [#28](https://github.com/pila86/1c-dev/issues/28) | stretch: `metadata.create` CommonModule | #23 |
| [#40](https://github.com/pila86/1c-dev/issues/40) | `metadata.update` — флаги CommonModule (stretch) | #28 |
