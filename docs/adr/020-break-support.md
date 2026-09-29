# ADR-020: Снятие конфигурации с поддержки (XML source)

**Статус:** Accepted  
**Дата:** 2026-09-27

## Контекст

После `project.import` типовой `.cf` в XML-выгрузке часто остаются артефакты поддержки поставщика (`ParentConfigurations.bin`, каталог `ParentConfigurations`). Пока они есть:

- объекты «на поддержке» нельзя свободно менять в конфигураторе;
- загрузка конфигурации из файлов (`ibcmd` `config import` / `build`) блокируется или ведёт себя как у конфигурации на поддержке.

Agent workflow M3 «import → metadata.update/create → build» на реальных типовых без снятия поддержки часто не проходит. Нужен явный, идемпотентный контракт в product API — без DESIGNER `/ManageCfgSupport`.

## Решение

### MVP (must): флаг на import

```bash
1c-dev configuration import --from configuration.cf --break-support
# MCP: configuration.import(..., break_support=true)
```

После `config export` в `source.path` — **source-level strip**:

1. Удалить файл(ы) настроек поддержки (`Ext/ParentConfigurations.bin` и/или фактический layout hierarchical dump).
2. Удалить каталог `ParentConfigurations` и связанные файлы поставщика в выгрузке.
3. Не изменять XML объектов метаданных.
4. Идемпотентно: нет артефактов → успех + diagnostic/warning «already off support».
5. Structured diagnostics: список удалённых путей.

Без `--break-support` артефакты (если были в `.cf`) **сохраняются** — opt-in, чтобы не терять возможность vendor-update у тех, кому она нужна.

### Should: отдельная команда

```bash
1c-dev source break-support
```

Для уже существующего XML (clone / dump без повторного import). Та же strip-логика, что post-step import.

Контракт и коды diagnostics — в реализации #74; расширение ADR-015 (`project.import` параметр `break_support`).

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| Source-level delete ParentConfigurations\* | Просто; совпадает с практикой XML-выгрузок; без DESIGNER | Теряется информация о поддержке целиком | **Принято** (MVP) |
| Всегда strip при любом import | Меньше флагов | Ломает сценарии «остаться на поддержке» | Отвергнуто |
| DESIGNER `/ManageCfgSupport` | «Официальный» путь платформы | Вне стека ibcmd; хрупкий batch | Отложено |
| Пообъектные правила в `ParentConfigurations.bin` | Тонкий контроль | Сложный формат; не нужен для adopt | Out of scope M3 |

## Последствия

- Типовой adopt: `configuration import --break-support` → правки metadata + `build` без блокировки поддержкой.
- Потеря возможности штатного обновления от поставщика для этого source — осознанный trade-off; документировать в CLI help / AGENTS.
- Unit-тесты на fixture с `ParentConfigurations.bin` без platform; integration на реальном типовом `.cf` — optional / skip без файла.

## Связанные решения

- [ADR-014](014-ibcmd-import-cf.md), [ADR-015](015-project-import-cf.md)
- Issue [#74](https://github.com/pila86/1c-dev/issues/74)
- [M3 Product adopt](../milestones/m3-product-adopt.md)
