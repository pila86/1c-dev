# ADR-012: Metadata read-backend MDClasses

**Статус:** Accepted  
**Дата:** 2026-09-19

## Контекст

Issue #21 требует `metadata.list` / `get` / `find` без платформы 1С: агент читает существующий XML source как Metadata IR v1 ([ADR-011](011-metadata-ir-v1.md)), не сырой XML. Write-path уже зафиксирован в [ADR-007](007-metadata-ir.md) (xml-gen). Для read нужен надёжный parser конфигурации (G7 / reuse-first), а не ad hoc XML в `core`.

## Решение

### Read-backend

Чтение метаданных — через библиотеку **MDClasses** (`io.github.1c-syntax:mdclasses`, LGPL-3.0, pin **0.20.0** на Maven Central).

Готового CLI у MDClasses нет. В репозитории — тонкий Gradle-инструмент `tools/md-reader`:

- `list <sourceDir>` → JSON-массив `{type, name, qname, synonym?}`
- `get <sourceDir> <QName>` → полный IR v1 (или stub для типов вне M2 write-набора)
- `find <sourceDir> <query>` → подмножество list по имени / синониму

Проекция MDClasses → IR v1 выполняется в Java (рядом с API типов). Python adapter только вызывает jar и парсит JSON.

Поток: `CLI/MCP` → `core.metadata` → `adapters.source.mdclasses` → `java -jar md-reader.jar …` → IR JSON.

### Поставка jar

Как xml-gen (вариант B из ADR-007): jar **не** в git.

- Исходники CLI: `tools/md-reader` (Gradle fatJar, зависимость `io.github.1c-syntax:mdclasses:0.20.0`)
- Скрипты: `scripts/fetch-md-reader.sh`, `scripts/fetch-md-reader.ps1` собирают jar и кладут в cache
- Cache: `~/.cache/1c-dev/tools/md-reader.jar` (Windows: `%LOCALAPPDATA%\1c-dev\tools\`)
- Override: `ONEC_MDREADER_JAR`
- Требуется JDK **21+** (MDClasses 0.20.0) и Gradle 8+ (зависимости — Maven Central при сборке)

Нет jar/JDK → diagnostic `1CM006`, exit `ENV_UNAVAILABLE`. Doctor: tool `md-reader`, capability `metadata.read`.

### Границы #21

- Только read (`list` / `get` / `find`) в core/CLI; MCP wrappers — [#26](https://github.com/pila86/1c-dev/issues/26)
- Source format M2: XML; EDT — после M4 (MDClasses умеет EDT, adapter пока xml-only по манифесту)
- Без публичного `source.write` и без парсинга XML в `core`

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| **A: MDClasses + thin CLI jar** | reuse-first; EDT-ready позже; зрелый parser | нужен JDK + fetch script | **Принято** |
| B: Python ElementTree в adapter | без Java для read | invent bicycle; расхождение с MDClasses | Отвергнуто |
| C: md-sparrow CLI as-is | готовый jar | другой IR/DTO; слабее семантика типов для IR v1 | Отложено |

## Последствия

- Onboarding: `./scripts/fetch-md-reader.sh` (или `.ps1`) один раз.
- Update pin MDClasses — смена версии в `tools/md-reader` + пересборка скриптом.
- `metadata.update` (#22) после записи вызывает `get` для заполнения `ir` в результате и agent flow; **не** для pre-check дублей (политика no-op → warning у xml-gen). Write остаётся xml-gen.

## Связанные решения

- ADR-007 (write xml-gen)
- ADR-011 (IR v1)
- Issue #21
- [M2 milestone](../milestones/m2-metadata-api.md)
