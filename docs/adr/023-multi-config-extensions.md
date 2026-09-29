# ADR-023: Multi-configuration и extensions

**Статус:** Accepted  
**Дата:** 2026-09-29

## Контекст

Schema `"1"` описывает один `source` и один `project.type`. Нужны несколько конфигураций в одном scope и расширения (разработка + загрузка в ИБ), в том числе test-extension для будущего test runner ([draft-tests](../milestones/draft-tests.md)).

## Решение

1. В манифесте schema `"2"`: массив **`configurations[]`** с полями `id`, `type`, `source` (`format`/`path`), опционально `default`, опционально **`extensions[]`**.
2. Элемент extension: `id`, `name` (имя для ibcmd `--extension`), `source`, опционально `purpose` (`product` | `tests` | …).
3. CLI/MCP: `--config` / `config_id`; default = configuration с `default: true` (ровно одна) или единственная configuration.
4. **`build`:** загрузить configuration, затем каждое extension в ИБ, выбранную через `runtimes[]` (ADR-026).
5. Adapter `platform_ibcmd`: поддержка `--extension` на import/apply/save/load/export (argv заморожены spike [#84](https://github.com/pila86/1c-dev/issues/84)).
6. Must: установка extension в ИБ из XML source. Should: из `.cfe` через `infobase config load --extension` (#95).
7. Scaffold: `templates/extension/` + `init --type extension` (standalone) и добавление extension в configuration-проект (`extension.add`). Lifecycle **configuration** (не extension): `configuration.add|list|…` ([ADR-027](027-configuration-lifecycle.md) / #100).
8. Связь с ИБ — только через `runtimes[]`, не поле `runtime:` у configuration.
9. `project.init` (type=configuration) создаёт empty scope без conf; вторая conf в том же scope — снова `configuration.add`, не `init` и не `extension.add`.

### Замороженный argv (8.3.25.x, spike #84)

Канон совместим с ADR-008 (`infobase config` + `config save`):

```text
ibcmd extension create --db-path=… --data=… --name=<Name> --name-prefix=<Prefix> [--purpose=add-on]
ibcmd infobase config import --db-path=… --data=… --extension=<Name> <xml_dir>
ibcmd infobase config apply  --db-path=… --data=… --extension=<Name> --force
ibcmd infobase config export --db-path=… --data=… --extension=<Name> <xml_dir>
ibcmd config save            --db-path=… --data=… --extension=<Name> --db <file.cfe>
ibcmd infobase config load   --db-path=… --data=… --extension=<Name> [--force] <file.cfe>
ibcmd infobase config check  --db-path=… --data=… --extension=<Name> [--force]
ibcmd extension list         --db-path=… --data=…
```

- `--extension` = имя расширения (`extensions[].name`), не manifest `id`.
- `extension create` до XML-import **не обязателен** (import/load сами создают расширение); create нужен, если заранее задаём prefix/purpose.
- Полный протокол и gaps: [docs/spikes/084-ibcmd-extension-ibsrv.md](../spikes/084-ibcmd-extension-ibsrv.md).

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| `configurations[]` + `extensions[]` в одном манифесте | Один scope, один detect | Сложнее schema | **Принято** |
| Только несколько отдельных `.1c-dev` без multi-config | Проще | Хуже DX «конфа + расширения» | Допустимо дополнительно; не вместо |
| Один source + extensions как «второй project.type» | Ближе к schema 1 | Не закрывает несколько conf | Отвергнуто |

## Последствия

- Metadata API получает `--config` для выбора source tree.
- Artifact `build --artifact cfe` для выбранного extension.
- Spike argv (#84) закрыт; реализация adapter/CLI — #88.
- Should #95: `extensions[].source.format=cfe` + `extension.add --from *.cfe`; `build` грузит через `infobase config load --extension` (нужен ibcmd с поддержкой `--extension` на load). Seed `.dt` — #111.

## Связанные решения

- ADR-008, ADR-014, ADR-015, ADR-022, ADR-026
- [M4](../milestones/m4-project-model.md)
- [Spike #84](../spikes/084-ibcmd-extension-ibsrv.md)
- [draft-tests](../milestones/draft-tests.md)
