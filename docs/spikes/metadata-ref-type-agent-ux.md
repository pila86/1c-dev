# DX: ссылочные типы в metadata.create / update для агентов

**Статус:** закрыто UX-фиксом в ветке `fix/metadata-ref-type-agent-ux` (2026-11-16): hint в `1CM004`, схема/пример Ref в `metadata.create`, fail-closed на `CatalogReference`, OpenCode IT `test_opencode_create_ref_dimension`.  
**Было:** наблюдение с агентного прогона (OpenCode + MCP `1c-dev`), 2026-11-16.  
**Связано:** [ADR-011 Metadata IR v1](../adr/011-metadata-ir-v1.md), `core/metadata/ir.py` (`_attribute_from_dict`, `parse_attr_spec`).

## Суть

Write регистров/реквизитов-ссылок **работает**, но контракт типов для агента неочевиден. Типичная модель подставляет платформенные литералы (`CatalogRef.X`, `СправочникСсылка.X`, `CatalogReference.X`) в поле `type` JSON `metadata.create` и получает `1CM004`. После нескольких ошибок делает ложный вывод «ссылки не поддерживаются» и уходит в типовую `.cf` / ручной XML — теряя фокус задачи.

## Симптом (воспроизведение)

Создать `AccumulationRegister` с измерением-ссылкой на справочник через MCP/JSON. Агент перебирает:

| `dimensions[].type` | Результат |
|---|---|
| `CatalogReference.Товары` | `1CM004` Неподдерживаемый тип атрибута |
| `СправочникСсылка.Товары` | то же |
| `CatalogRef.Товары` | то же |
| `Catalog.Товары` | то же |

Дальше типичный escape hatch:

1. create объекта **без** ссылочного измерения/реквизита;
2. вывод «DSL не умеет ссылки»;
3. импорт типовой `.cf`, grep `cfg:CatalogRef.…`, правка XML;
4. то же на ТЧ документа: fail → create со `String` → поздний patch.

Итог может быть зелёным (build/check ok, в XML уже `cfg:CatalogRef.…`), но путь — обход контракта MCP, а не его использование.

## Корневая причина

В **JSON create / IR** ссылка задаётся так:

```json
{
  "name": "Товар",
  "type": "Ref",
  "reference": "Catalog.Товары"
}
```

Допустимые `type`: только `String` | `Number` | `Boolean` | `Date` | `Ref`.  
`CatalogRef.X` в поле `type` для `_attribute_from_dict` **невалиден**.

Параллельно существует **другой** shorthand (CLI update / xml-gen):  
`Товар:CatalogRef.Товары` → в XML `cfg:CatalogRef.Товары`.

Агент смешивает три нотации:

- платформенные имена (`CatalogRef`, `СправочникСсылка`, `CatalogReference`);
- xml-gen update shorthand;
- IR JSON (`Ref` + `reference`).

Канонический create (`type: Ref` + `reference`) в наблюдении **не пробовался**.

Вредный сигнал: `metadata_update` с кривым литералом вроде `ТестСсылка:CatalogReference.Товары` может вернуть `status: ok`, записать в XML `cfg:CatalogReference.…`, а IR показать `type: Ref`. Агент читает это как «ссылки вроде работают, IR врёт» и усиливает уход в XML.

## Потеря контекста

Не сбой сессии, а смена цели после серии `1CM004`:

| Было | Стало |
|---|---|
| прикладная задача (метаданные + код) | археология XML типов |
| MCP `metadata.*` | bash + `.cf` + grep |
| контракт IR | «что съест платформа/xml-gen» |

## Что улучшить

1. **`1CM004` при `CatalogRef.X` / `CatalogReference.X` / `СправочникСсылка.X` в `type`** — hint:  
   `используйте {"type":"Ref","reference":"Catalog.X"}`; для update — `Name:CatalogRef.X` или `Name:Ref:Catalog.X`.
2. **Схема MCP `metadata_create`:** явно enum типов + обязательный `reference` при `Ref` (в т.ч. для `dimensions` / attrs ТЧ).
3. Fail-closed: не принимать и не «успешно» писать `CatalogReference` в XML.
4. В описании tool / AGENTS — один пример create с Ref (измерение или реквизит), без доменной нагрузки.
5. Выровнять docs и интеграционные сценарии с одним каноническим литералом.

## Вердикт

| Вопрос | Ответ |
|---|---|
| Сломан ли write ссылок/регистров? | Нет: Ref достижим через IR и `CatalogRef` shorthand |
| Почему агент «не может»? | Неверный литерал в JSON create + мягкий ok на кривом update |
| Почему лезет в типовую? | Escape hatch после ложного вывода о неподдержке |
| Приоритет | DX ошибок и схемы MCP, единый канон типов |
