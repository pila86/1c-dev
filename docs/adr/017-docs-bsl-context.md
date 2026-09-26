# ADR-017: Documentation API via bsl-context

**Статус:** Accepted  
**Дата:** 2026-09-26

## Контекст

[M3](../milestones/m3-product-adopt.md) требует локальный индекс синтакс-помощника платформы для агента: `docs.search` / `docs.get` (CLI + MCP). Агент не должен получать весь индекс в system prompt — только по запросу tool. Источник знаний — HBK установленной платформы; готовой CLI у [bsl-context](https://github.com/1c-syntax/bsl-context) нет. Слот jar `docs-facade` в [ADR-013](013-packaging-toolchain-cache.md) был `deferred` до #51.

## Решение

### Backend

Тонкий Gradle fatJar `tools/docs-facade` поверх **bsl-context** pin **0.10.0** (Maven Central, JDK 21+):

| Команда | Назначение |
|---------|------------|
| `ensure` | Построить/проверить on-disk индекс |
| `search` | Поиск по готовому индексу |
| `get` | Карточка по имени / `Owner.Member` |

Контракт: argv + одна JSON-строка на stdout (как md-reader, [ADR-012](012-metadata-read-mdclasses.md)).

Python: `CLI/MCP` → `core.docs` → `adapters.docs` → `java -jar docs-facade.jar …`.

### Индекс

```text
{cache_root}/docs/{platform.version}/
  meta.json    # version, HBK path/mtime/size, facade pin, builtAt
  index.json   # плоский searchable dump
```

Ключ — `platform.version` из `1c.project.yaml` (major.minor.build, например `8.3.27`). Индекс строится **lazy** при первом `docs.search` / `docs.get`. Явный `docs build-index` — out of scope M3.

### HBK discovery

Владеет Python (совпадает с doctor / platform discovery), не `PlatformContextGrabber.autoDetect`:

1. `ONEC_HBK_PATH`
2. `{platform.path}/shcntx_ru.hbk` и `{platform.path}/bin/shcntx_ru.hbk`

В jar передаётся `--hbk` или `--platform-bin`.

### Поставка

- `tools sync`: local-build → user cache `docs-facade.jar` / `docs-facade-bsl-context-0.10.0.jar`
- Soft-компонент (как bsl-ls): сбой сборки не валит overall sync
- Override: `ONEC_DOCS_FACADE_JAR`
- Нет HBK / JDK / jar → structured diagnostic (`1CX…`), без падения без payload

### Границы M3

Must: `docs.search`, `docs.get`.  
Out of scope: `docs.related`, `docs.version`, явный `docs build-index`, vector DB / embeddings.

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| **A: bsl-context + thin facade jar** | reuse-first; полный СП | JDK 21+; сборка jar | **Принято** |
| B: парсить HBK на Python | без Java для docs | reinvent; расхождение с BSL LS | Отвергнуто |
| C: ходить в онлайн-СП 1С | без локального индекса | сеть; нестабильный HTML | Отвергнуто |

## Последствия

- `tools sync` больше не помечает docs-facade как deferred.
- Первый `docs.*` на машине может занять ~1–2 с на парсинг HBK; в JSON — info-diagnostic.
- Смена pin bsl-context — обновить `tools/docs-facade` + `toolchain/manifest.yaml` и пересобрать.

## Связанные решения

- [ADR-013](013-packaging-toolchain-cache.md) (cache layout / pin toolchain)
- [ADR-012](012-metadata-read-mdclasses.md) (образец thin Java CLI)
- Issue [#51](https://github.com/pila86/1c-dev/issues/51)
- [M3 milestone](../milestones/m3-product-adopt.md)
