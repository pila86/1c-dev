# ADR-023: Multi-configuration и extensions

**Статус:** Proposed  
**Дата:** 2026-09-29

## Контекст

Schema `"1"` описывает один `source` и один `project.type`. Нужны несколько конфигураций в одном scope и расширения (разработка + загрузка в ИБ), в том числе test-extension для будущего test runner ([draft-tests](../milestones/draft-tests.md)).

## Решение

1. В манифесте schema `"2"`: массив **`configurations[]`** с полями `id`, `type`, `source` (`format`/`path`), опционально `default`, опционально **`extensions[]`**.
2. Элемент extension: `id`, `name` (имя для ibcmd `--extension`), `source`, опционально `purpose` (`product` | `tests` | …).
3. CLI/MCP: `--config` / `config_id`; default = configuration с `default: true` (ровно одна) или единственная configuration.
4. **`build`:** загрузить configuration, затем каждое extension в ИБ, выбранную через `runtimes[]` (ADR-026).
5. Adapter `platform_ibcmd`: поддержка `--extension` на import/apply/save/load/export (точные argv — spike на целевой платформе до freeze).
6. Must: установка extension в ИБ из XML source. Should: из `.cfe`, если платформа умеет (`config update` и т.п.).
7. Scaffold: `templates/extension/` + `init --type extension` (standalone) и добавление extension в configuration-проект.
8. Связь с ИБ — только через `runtimes[]`, не поле `runtime:` у configuration.

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| `configurations[]` + `extensions[]` в одном манифесте | Один scope, один detect | Сложнее schema | **Принято (Proposed)** |
| Только несколько отдельных `.1c-dev` без multi-config | Проще | Хуже DX «конфа + расширения» | Допустимо дополнительно; не вместо |
| Один source + extensions как «второй project.type» | Ближе к schema 1 | Не закрывает несколько conf | Отвергнуто |

## Последствия

- Metadata API получает `--config` для выбора source tree.
- Artifact `build --artifact cfe` для выбранного extension.
- Перед реализацией — spike `ibcmd … --extension`.

## Связанные решения

- ADR-008, ADR-014, ADR-015, ADR-022, ADR-026
- [M4](../milestones/m4-project-model.md)
- [draft-tests](../milestones/draft-tests.md)
