# ADR-007: Metadata IR v0 + write-backend xml-gen

**Статус:** Accepted  
**Дата:** 2026-09-17

## Контекст

Issue #5 и M1 требуют semantic write-path: агент/CLI создаёт `Catalog` с реквизитами в `src/` без ручного XML. PRD §17 задаёт format-independent IR; §7.5 и G7 — не изобретать metadata tooling с нуля. MDClasses (1c-syntax) только читает конфигурацию и не подходит для create.

Нужны: минимальный IR v0, CLI `metadata create`, один write-path без публичного `source.write`.

## Решение

### IR v0

Format-independent модель (минимум для M1):

- объект: `type` (`Catalog`), `name`, `synonym?`, `attributes[]`
- атрибут: `name`, `synonym?`, `type` ∈ `{String, Number}`
  - String: `length`
  - Number: `precision`, `scale`
- qualified name: `Catalog.Products`

### Write-backend

Физическая запись XML — через **xml-gen** (`meta compile`, LGPL-3.0) из
[SteelMorgan/1c-agent-based-dev-framework](https://github.com/SteelMorgan/1c-agent-based-dev-framework) `tools/xml-gen`.

Поток: IR → JSON DSL xml-gen → subprocess `java -jar … meta compile` → файлы в `source.path` + регистрация в `Configuration.xml`.

Поставка (вариант B): jar **не** в git. Скрипты `scripts/fetch-xml-gen.sh` (Linux/macOS) и `scripts/fetch-xml-gen.ps1` (Windows) собирают pinned commit в cache:

- Linux/macOS: `~/.cache/1c-dev/tools/xml-gen.jar`
- Windows: `%LOCALAPPDATA%\1c-dev\tools\xml-gen.jar`
- override: `ONEC_XMLGEN_JAR`

Pin SHA и discovery — в `adapters/source/xmlgen`. Нет jar/JDK → diagnostic `1CM006`, exit `ENV_UNAVAILABLE`.

### Границы M1

- Только `metadata.create`, только `Catalog`
- Без публичного `source.write`
- MDClasses / metadata list|get — позже (M2+)

## Альтернативы

Bake-off 2026-09-17 (сценарий: `Catalog.Products`, synonym «Товары», `Article` String(50); база после `1c-dev init`, dump 2.17; платформа 8.3.25 / `ibcmd`):

| Кандидат | Создание | JDK / jar | ibcmd import/check/apply | Вердикт |
|----------|----------|-----------|--------------------------|---------|
| **xml-gen** `meta compile` | 1 шаг, JSON≈IR | 17+ / ~6.7 MB | OK | **Принято** |
| **md-sparrow** | 3 шага (object → attr → set DTO) | 21 / ~24 MB | OK | Отложено (XSD/read позже) |
| Свои `Catalog.xml.tmpl` | полный контроль в Python | — | не гонялся | Отвергнуто (G7) |

Поставка jar:

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| A: jar в `third_party/` | сразу после clone | бинарь в git | Отвергнуто |
| **B: fetch script + cache** | нет бинаря; pin SHA | нужен JDK при первой сборке | **Принято** |
| C: git submodule `tools/xml-gen` | исходники рядом | submodule + JDK | Отвергнуто |

## Последствия

- `1c-dev metadata create` и будущий MCP `metadata.create` используют один core API.
- Doctor показывает `java` / `xml-gen` и capability `metadata.create`.
- Onboarding: один раз `./scripts/fetch-xml-gen.sh` или `pwsh scripts/fetch-xml-gen.ps1`.
- Обновление xml-gen — смена pin SHA + пересборка скриптом.

## Связанные решения

- ADR-002, ADR-003, ADR-006
- [ADR-011](011-metadata-ir-v1.md) — модель IR для M2+ (v1); этот ADR остаётся про IR v0 и write-backend xml-gen
- Issue #5
- PRD §16–§17, §69.5
