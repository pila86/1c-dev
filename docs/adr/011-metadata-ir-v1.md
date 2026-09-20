# ADR-011: Metadata IR v1

**Статус:** Accepted  
**Дата:** 2026-09-19

## Контекст

ADR-007 зафиксировал IR v0 (`Catalog` + `String`/`Number`) и write-backend xml-gen для M1. M2 требует единую semantic-модель для `list` / `get` / `find` / `update` / `create` / `delete` и типы шире Catalog (Document, Enum, регистры) без сырого XML.

Нужен контракт IR v1 до реализации reader/write (#21–#24, delete).

## Решение

### Общая форма объекта

Format-independent JSON (пример каркаса):

```json
{
  "type": "Catalog",
  "name": "Products",
  "synonym": "Товары",
  "attributes": [],
  "tabularSections": []
}
```

- Qualified name: `{type}.{name}` (`Document.Sales`, `InformationRegister.Prices`, …).
- `metadata.list` возвращает минимум `{type, name, qname}` (+ `synonym` при наличии).
- `metadata.get` возвращает полный IR объекта.

Поддерживаемые `type` в M2: `Catalog`, `Document`, `Enum`, `InformationRegister`, `AccumulationRegister`, `CommonModule` (stretch create, #28).

### Атрибуты

| `type` | Поля | Пример CLI `--attr` |
|--------|------|---------------------|
| `String` | `length` (default 10) | `Article:String:50:Артикул` |
| `Number` | `precision`, `scale` | `Price:Number:15.2:Цена` |
| `Boolean` | — | `IsActive:Boolean::Активен` |
| `Date` | — | `SaleDate:Date::Дата` |
| `Ref` | `reference` = QName цели | `Counterparty:Ref:Catalog.Counterparties:Контрагент` |

Обратная совместимость с IR v0: `String` / `Number` без изменений.

JSON-пример атрибута-ссылки:

```json
{
  "name": "Counterparty",
  "type": "Ref",
  "reference": "Catalog.Counterparties",
  "synonym": "Контрагент"
}
```

### Tabular sections

Общая конструкция для **Catalog и Document** (не «только Document»):

```json
{
  "name": "Products",
  "synonym": "Товары",
  "attributes": []
}
```

В M2 приоритет write-сценария: Document + ТЧ. Catalog + ТЧ — та же модель IR; реализация write/update по мере поддержки backend.

### Специализации типов

- **Catalog / Document:** `attributes[]`, `tabularSections[]?`
- **Enum:** `values[]` = `{name, synonym?}` (без `attributes` / ТЧ)
- **InformationRegister / AccumulationRegister** (упрощённо): `dimensions[]`, `resources[]` — элементы той же формы, что Attribute (включая `Ref`). Периодичность / вид регистра и пр. — out of scope M2.
- **CommonModule** (stretch create #28): контекстные флаги; без `attributes` / ТЧ / values / dimensions / resources. Тело BSL при create — пустой `Module.bsl` (запись процедур — later). Изменение флагов существующего модуля — `metadata.update` через `set-flag` → `modify-property` ([#40](https://github.com/pila86/1c-dev/issues/40)).

Пример Enum:

```json
{
  "type": "Enum",
  "name": "OrderStatuses",
  "synonym": "СтатусыЗаказа",
  "values": [
    {"name": "New", "synonym": "Новый"},
    {"name": "Done", "synonym": "Выполнен"}
  ]
}
```

Пример регистра:

```json
{
  "type": "InformationRegister",
  "name": "Prices",
  "dimensions": [
    {
      "name": "Product",
      "type": "Ref",
      "reference": "Catalog.Products"
    }
  ],
  "resources": [
    {
      "name": "Price",
      "type": "Number",
      "precision": 15,
      "scale": 2
    }
  ]
}
```

Пример CommonModule:

```json
{
  "type": "CommonModule",
  "name": "SalesServer",
  "synonym": "ПродажиСервер",
  "server": true,
  "serverCall": false,
  "clientManagedApplication": false,
  "clientOrdinaryApplication": false,
  "externalConnection": false,
  "privileged": false,
  "global": false,
  "returnValuesReuse": "DontUse"
}
```

В create DSL в xml-gen уходят **только явно заданные** флаги. Сахар JSON/CLI: `client` → `clientManagedApplication`. Допустимые `returnValuesReuse`: `DontUse`, `DuringRequest`, `DuringSession`.

### Семантика `metadata.update`

- Цель: существующий объект по QName.
- Модель операций (как у xml-gen `meta edit`), не «только add»:
  - `add-attribute` / `modify-attribute` / `remove-attribute`
  - `add-ts` / `modify-ts` / `remove-ts` / `add-ts-attribute` / `remove-ts-attribute`
  - `add-enumValue` / `modify-enumValue` / `remove-enumValue` (#39)
  - `add-dimension` / `modify-dimension` / `remove-dimension` (#39)
  - `add-resource` / `modify-resource` / `remove-resource` (#39)
  - `modify-property` для флагов `CommonModule` (#40); публичный сахар `set-flag` (IR/CLI имена `server=true`, …) ремапится в core в `modify-property` с Designer-именами (`Server=true`). Тело `Module.bsl` не меняется.
- Типы update: `Catalog`, `Document`, `Enum`, `InformationRegister`, `AccumulationRegister`, `CommonModule`.
- No-op backend (дубль add, modify/remove несуществующего) → `status=ok`, diagnostic `severity=warning`, source не менялся; CLI exit = SUCCESS.
- Объект / файл не найден → `status=error`, diagnostic (например `1CM008`), source intact.
- Пустой список операций → `status=error`.
- Удаление **атрибута** / values / dimensions / resources — через `update` + `remove-*`, не через `metadata.delete`.
- Без публичного `source.write`.

### Семантика `metadata.delete`

- Цель M2 must: **целый объект** по QName.
- Удаляет артефакты объекта из `source.path` и регистрацию в `Configuration.xml`.
- Объект не найден → structured diagnostic, source не меняется.
- Без cascade по ссылкам (битые `Ref` после delete допустимы до graph / M6).
- После delete: `metadata.get` → not found; `list` не содержит объект.
- Nested delete атрибутов / values / dimensions / resources — через `metadata.update` (`remove-*`), не must `metadata.delete`.

### Write-backend

Физическая запись/удаление в XML остаётся через путь из ADR-007 (xml-gen и согласованные мутации `Configuration.xml`). Публичный `source.write` не вводим.

### Out of scope M2

- Import `.cf` / install / docs (→ M3); EDT / `source.convert` (→ M4)
- Graph API: `references` / `dependencies` / `impact` (→ M6)
- Публичный `source.write`
- Полное покрытие видов метаданных платформы
- Расширения (`project.type: extension`)
- Запись тела BSL / процедур модуля (узкий write later)
- Nested delete через `metadata.delete` (атрибуты / ТЧ / values / dimensions / resources — через `update`)

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| A: расширить ADR-007 in-place | один документ | смешивает историю M1 и контракт M2 | Отвергнуто |
| **B: новый ADR-011 (IR v1)** | чистый контракт для #21+; 007 остаётся про xml-gen | два ADR по metadata | **Принято** |
| C: сырой XML / EDT в API | «честное» представление | ломает format-independence (PRD §17) | Отвергнуто |

## Последствия

- Reader (#21) отдаёт IR v1; create/update (#22–#24) и delete принимают/соблюдают этот контракт.
- CLI и MCP используют один `core.metadata` API.
- Doctor write-capabilities (`metadata.create` / `update` / `delete`) несут `supportedTypes` из констант IR (#25).
- Реализация кода IR/delete — в follow-up issues, не в #20.

## Связанные решения

- ADR-007 (IR v0 + xml-gen; модель IR для M2+ — этот ADR)
- Issue #20
- [M2 milestone](../milestones/m2-metadata-api.md)
- PRD §16–§18, §47
