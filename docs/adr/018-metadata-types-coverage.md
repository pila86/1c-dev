# ADR-018: Metadata types coverage (23 meta + Subsystem)

**Статус:** Accepted  
**Дата:** 2026-09-27

## Контекст

[ADR-011](011-metadata-ir-v1.md) зафиксировал IR v1 для M2: шесть write-типов
(`Catalog`, `Document`, `Enum`, `InformationRegister`, `AccumulationRegister`,
`CommonModule`). Write идёт через xml-gen `meta compile` / `edit` / `remove`
([ADR-007](007-metadata-ir.md)); read — через md-reader / MDClasses
([ADR-012](012-metadata-read-mdclasses.md)).

Upstream xml-gen уже поддерживает **23** типа Meta DSL и отдельно домен
**Subsystem** (`subsystem compile` / `edit`). Агент на реальных конфигурациях
(после import в M3) упирается в «unsupported type». Нужен контракт расширения
без смешения с must-acceptance Product adopt.

## Решение

### Цель покрытия

| В scope | Вне scope |
|---------|-----------|
| 23 типа Meta DSL xml-gen | Role, Form, Command, SessionParameter, FunctionalOption, XDTOPackage, … |
| `Subsystem` | `xml-gen interface edit` (CommandInterface) — later |
| Sync **create + get (full IR) + update + delete** на тип | Cascade delete / reference graph (→ M6) |

Список Meta DSL (23): Catalog, Document, Enum, Constant, InformationRegister,
AccumulationRegister, AccountingRegister, CalculationRegister, ChartOfAccounts,
ChartOfCharacteristicTypes, ChartOfCalculationTypes, BusinessProcess, Task,
ExchangePlan, DocumentJournal, Report, DataProcessor, CommonModule, ScheduledJob,
EventSubscription, HTTPService, WebService, DefinedType.

### Sync reader ↔ writer

На каждый тип в одной поставке:

1. **create** — IR → xml-gen (или subsystem compile)
2. **get** — md-reader full IR (не stub summary)
3. **update** — ops через xml-gen `meta edit` или `subsystem edit`
4. **delete** — удаление объекта из source + `Configuration.xml`

Doctor `supportedTypes` для `metadata.create` / `update` / `delete` берётся из
одного allowlist в IR (расширение констант ADR-011).

### Subsystem — отдельный write-path

Не `meta compile`. Адаптер вызывает:

- create: `xml-gen subsystem compile <json> <sourceDir>`
- update: `xml-gen subsystem edit …` (`add-content` / `remove-content` /
  `add-child` / `remove-child` / `set-property`)
- IR минимум: `type`, `name`, `synonym?`, `content[]`, `children[]`,
  `includeInCommandInterface?`

### Milestone

Трек временно в [M3](../milestones/m3-product-adopt.md) как **should** (не
блокирует #52). Возможен перенос в отдельный milestone.

Волны реализации (GitHub issues): [#60](https://github.com/pila86/1c-dev/issues/60)
foundation → [#61](https://github.com/pila86/1c-dev/issues/61) CommonModule get →
[#62](https://github.com/pila86/1c-dev/issues/62) Subsystem →
[#63](https://github.com/pila86/1c-dev/issues/63)–[#69](https://github.com/pila86/1c-dev/issues/69)
meta waves → [#70](https://github.com/pila86/1c-dev/issues/70) docs →
[#71](https://github.com/pila86/1c-dev/issues/71) E2E acceptance.

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| **A: цель = 23 meta + Subsystem** | паритет с xml-gen; Subsystem нужен агенту | не вся платформа | **Принято** |
| B: только 23 meta, без Subsystem | проще (один CLI-домен) | дыра в навигации конфигурации | Отвергнуто |
| C: весь каталог MDClasses | «полное» покрытие | нет write в xml-gen; огромный объём | Отвергнуто |
| D: расширять только create, get stub | быстрее | ломает agent flow get→update | Отвергнуто |

## Последствия

- ADR-011 остаётся контрактом IR v1 для M2-типов; этот ADR — политика coverage
  и Subsystem write-path.
- Pin xml-gen должен покрывать meta 23 и subsystem compile/edit.
- Реализация — отдельными issues/PR по волнам; этот ADR не включает код.

## Связанные решения

- [ADR-007](007-metadata-ir.md), [ADR-011](011-metadata-ir-v1.md),
  [ADR-012](012-metadata-read-mdclasses.md)
- [M3 track E](../milestones/m3-product-adopt.md)
- Issues [#60](https://github.com/pila86/1c-dev/issues/60)–[#71](https://github.com/pila86/1c-dev/issues/71)
- SteelMorgan xml-gen Meta DSL / subsystem-operations
