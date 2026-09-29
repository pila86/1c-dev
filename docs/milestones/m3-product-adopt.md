# M3: Product adopt (CF import + install + ide configure)

**Статус:** Done — acceptance E2E [#52](https://github.com/pila86/1c-dev/issues/52) (`tests/test_m3_acceptance.py`). Треки A–D и E (#45–#51, #60–#71, #74, #76) **done**.

## Goal

Инструмент можно поставить в user cache / PATH **вместе с зависимостями toolchain** (xml-gen, md-reader/MDClasses, …) и начать использовать на **реальной** конфигурации без копирования monorepo: импорт из `.cf`, scaffold IDE/агента в каталоге проекта, подключение BSL LS MCP и локальный индекс знаний о платформе (через bsl-context).

## Prerequisites

- M1 зелёный: `init` → `metadata.create(Catalog)` → `build` → `check`
- M2: Metadata API (list/get/find + update / create beyond Catalog / delete) по XML source
- Платформа 1С 8.3.x, `ibcmd` в PATH (для import / build / check)
- JDK 17+ (xml-gen) и JDK 21+ (md-reader; bsl-context / BSL LS — тоже 21+)

## Decisions

| Тема | Решение |
|------|---------|
| Packaging | **must:** `uv tool install` из git/wheel; layout cache + pin — [ADR-013](../adr/013-packaging-toolchain-cache.md); PyPI / pipx / single-binary — later, не acceptance M3 |
| `runtime.load` | **should:** CLI желателен; MCP — later |
| IDE в `ide configure` | **must:** `cursor` и `kilocode`; путь/формат MCP Kilocode — по доке при реализации |
| `ide configure` без `--force` | безопасный merge (см. трек C); `--force` = полная перезапись шаблонных артефактов |
| `import` vs `ide configure` | раздельно: import = CF → XML + манифест; агентские файлы (`AGENTS.md`, MCP IDE) — только `ide configure` |
| Dirty source | конфликт = в `source.path` уже есть `Configuration.xml`; без `--force` — отказ, source intact |
| Break support | **must:** opt-in `--break-support` на `project.import` — source-level strip `ParentConfigurations*` после export ([ADR-020](../adr/020-break-support.md)); без флага артефакты сохраняются; should: `source break-support`; пообъектные правила / DESIGNER `/ManageCfgSupport` / vendor-update — later |
| Project clean | **should:** `project clean --yes` всегда сносит `source.path` **и** `.runtime/` ([ADR-021](../adr/021-project-clean.md)); манифест / IDE / git не трогает; без `--yes` — отказ; `runtime.reset` (только IB) — later |
| Docs index | **lazy-only** при первом `docs.search` / `docs.get`; явный `docs build-index` — later |
| Тест import | round-trip: `build --artifact cf` → `project.import`; skip без platform; бинарный `.cf` в git не коммитим |

## Scope

Четыре трека. EDT **не** входит (→ [draft-source-formats](draft-source-formats.md)).

### A. Import из `.cf` (CF → XML source)

Bootstrap существующей конфигурации: бинарный `.cf` → file IB → выгрузка в `source.path`.

`.cf` — **входной** артефакт (не source of truth). Дальше истина — Git + XML source проекта.

`import` **не** пишет агентские артефакты (`AGENTS.md`, MCP IDE) — для этого отдельный `ide configure` (трек C).

Pipeline (ibcmd):

```text
create IB (если нет)
  → config load <file.cf>
  → config apply
  → config export → source.path
  → [если --break-support] strip ParentConfigurations* в source.path
```

Публичный контракт (**must**):

```bash
1c-dev project import --from configuration.cf
1c-dev project import --from configuration.cf --break-support   # типовые на поддержке
# MCP: project.import  (+ break_support: bool)
```

Типовые `.cf` после export часто содержат настройки поддержки поставщика (`Ext/ParentConfigurations.bin`, каталог `ParentConfigurations`). Пока они есть, нельзя свободно править объекты и мешает загрузка конфигурации из файлов (`build`). `--break-support` (**must**, [ADR-020](../adr/020-break-support.md)) — идемпотентный source-level strip этих артефактов после export; объекты метаданных не трогает. Без флага артефакты сохраняются (сценарии vendor-update).

Узкий шаг только CF → IB, без dump в source (**should**, CLI; MCP later):

```bash
1c-dev runtime load --from configuration.cf
```

Отдельный strip для уже существующего XML (**should**):

```bash
1c-dev source break-support
```

Конфликт без `--force`: в `source.path` уже есть `Configuration.xml` → structured diagnostic, source не затёрт. Пустой / отсутствующий `source.path` — import ок. После `init` (там уже есть `Configuration.xml`) нужен `--force`.

Явный wipe перед повторным import/init (**should**, [ADR-021](../adr/021-project-clean.md)):

```bash
1c-dev project clean --yes
# MCP: project.clean  (confirm / yes обязателен)
```

Удаляет содержимое `source.path` **и** весь `.runtime/` (IB, ibcmd-data, client state). Не трогает `1c.project.yaml`, `AGENTS.md`, IDE MCP, `.gitignore`. Без `--yes` — отказ. Живой runtime-клиент — stop или отказ с suggestion. Идемпотентно. Отличие от `import --force`: force перезаписывает через pipeline; clean — destructive reset. `tools clean` — другое пространство (user cache toolchain).

### B. User-level install (cache + PATH + toolchain deps)

Установка CLI **без** `poetry run` и без клонирования репозитория рядом с продуктом. Python-пакет — только оркестратор: **вместе с установкой (или сразу после неё) в user cache должны подтягиваться нативные зависимости toolchain**, сейчас раздаваемые вручную через `scripts/fetch-*.sh`.

Целевой UX (**must**):

```bash
# один раз
uv tool install git+https://github.com/pila86/1c-dev   # или из локального wheel
1c-dev tools sync                                      # jars в user cache
1c-dev doctor
```

Имя команды и layout cache — [ADR-013](../adr/013-packaging-toolchain-cache.md): `1c-dev tools sync`, cache `~/.cache/1c-dev` (Windows: `%LOCALAPPDATA%\1c-dev`).

`1c-dev tools sync` — идемпотентный bootstrap toolchain в user-dir:

| Компонент | Зачем | Примечание |
|-----------|--------|------------|
| **xml-gen** jar | `metadata.create` / `update` | сейчас `scripts/fetch-xml-gen.sh`, JDK 17+ |
| **md-reader** jar (+ **MDClasses** на classpath / shaded) | `metadata.list` / `get` / `find` | сейчас `scripts/fetch-md-reader.sh`, JDK 21+ |
| **bsl-language-server** jar | MCP анализа BSL (трек D1) | скачать release в тот же cache |
| **docs facade** (bsl-context) | `docs.search` / `get` (трек D2) | jar поверх bsl-context; индекс HBK — **lazy** при первом `docs.*` |

Ожидания:

- entrypoint `1c-dev` в PATH пользователя через `uv tool install`
- кэш toolchain в user-dir (например `~/.cache/1c-dev` / `~/.local/share/1c-dev`), с версионированием артефактов (pin / checksum в манифесте toolchain)
- **после `tools sync`** `metadata.create` / `list` / `get` работают без ручного `./scripts/fetch-*.sh` и без checkout monorepo
- `doctor` проверяет self (CLI, **каждый** jar toolchain, Java, platform, ibcmd) и умеет подсказать / запустить докачку (`--fix` или отсылка к `tools sync`)
- override путей через env (`ONEC_XMLGEN_JAR`, `ONEC_MDREADER_JAR`, …) сохраняется и имеет приоритет над cache
- сеть недоступна / JDK нет → structured diagnostic, CLI при этом остаётся usable для команд без jar

ADR packaging: [ADR-013](../adr/013-packaging-toolchain-cache.md) — `uv tool` must, layout cache, pin toolchain; pipx / PyPI — later. Single-binary не must M3. Maven Central / GitHub Releases как источники jar — reuse текущих fetch-скриптов, но вызов из `tools sync`, не из README «вручную».

### C. IDE configure (манифест + агенты + IDE MCP)

Идемпотентная установка артефактов **в каталог проекта** (существующий Git-репозиторий конфигурации), без копирования monorepo:

```bash
1c-dev ide configure [--target all|cursor|kilocode|none] [--force]
# MCP: ide.configure
```

`--target`: **must** `cursor` и `kilocode` (плагин VS Code); default `all`. Путь/формат MCP-конфига Kilocode — по [ADR-016](../adr/016-ide-configure.md).

Политика без `--force` (безопасный merge):

| Артефакт | Без `--force` | С `--force` |
|----------|---------------|-------------|
| файл отсутствует | создать из шаблона | то же |
| `.gitignore` | дописать только недостающие строки | перезаписать шаблоном (с diagnostic) |
| IDE MCP config | добавить servers `1c-dev` / `bsl-language-server`, если их ещё нет; чужие servers и уже заданные — не трогать | перезаписать шаблоном |
| `AGENTS.md` | skip + warning (пользовательский текст) | перезаписать шаблоном |
| `1c.project.yaml` | не перезаписывать существующие поля; только недостающие обязательные (если трогаем) | осторожно: не клоббировать source/runtime без явной семантики; предпочтительно validate |

Отличие от `init`: `init` — bootstrap **пустой** конфигурации и сразу пишет IDE MCP (default `--ide-target all`); `ide configure` — подключить runtime к **уже существующему** source (после import или clone) и повторный merge. `import` `ide configure` не вызывает.

### D. Agent knowledge: BSL LS MCP + docs/context (bsl-context)

Два слоя — не смешивать в один MCP без ADR.

#### D1. BSL Language Server MCP (reuse)

BSL LS уже умеет режим MCP (`java -jar bsl-language-server.jar mcp`). В M3:

- doctor: обнаружить / скачать jar BSL LS в user cache
- `ide configure --target …`: прописать отдельный MCP server рядом с `1c-dev`
- `AGENTS.md`: когда использовать tools `1c-dev.*` vs анализ BSL через bsl-ls

Собственные MCP-обёртки над LSP API (`bsl.analyze`, …) и unified MCP — **out of scope** M3 (PRD open Q#16 → later / ADR).

#### D2. Documentation / platform context API (bsl-context)

Локальный индекс синтакс-помощника по версии платформы ([bsl-context](https://github.com/1c-syntax/bsl-context), PRD §20–§21):

```text
Installed platform HBK
  → bsl-context (Java facade / jar)
  → cache index keyed by platform.version
  → docs.search / docs.get (+ MCP)
```

Минимальный публичный контракт (**must**):

```bash
1c-dev docs search "ТаблицаЗначений"
1c-dev docs get "Массив.Добавить"
# MCP: docs.search, docs.get
```

Индекс строится **lazy** при первом `docs.search` / `docs.get` (явный статус в JSON/diagnostic при долгой индексации). Нет HBK / JDK → skip + diagnostic. Явный `docs build-index`, `docs.related`, `docs.version` — **out of scope** M3.

Источник знаний для агента: глобальный контекст, типы/методы/свойства, языковые конструкции, при необходимости — элементы языка запросов. Не заливать весь индекс в system prompt — только по запросу tool.

### E. Metadata types coverage (should, temporary)

Расширение Metadata API до **паритета с xml-gen**: 23 типа Meta DSL + **`Subsystem`** (отдельный CLI-путь `subsystem compile` / `edit`). Контракт: [ADR-018](../adr/018-metadata-types-coverage.md).

На каждый тип синхронно: **create + get (full IR) + update + delete** (md-reader ↔ xml-gen).

| Приоритет | Статус в M3 |
|-----------|-------------|
| **should** | **done** (#60–#71); **не** блокировал must-acceptance треков A–D / #52 |
| Temporary | При необходимости трек целиком переносится в отдельный milestone |

Уже в M2 (CRUD + full get): Catalog, Document, Enum, InformationRegister, AccumulationRegister. CommonModule — CRUD + full get (E0 / #61). Subsystem — CRUD + full get (E1 / #62). Constant + DefinedType — CRUD + full get (E2 / #63). Report + DataProcessor — CRUD + full get (E3 / #64). ScheduledJob + EventSubscription — CRUD + full get (E4 / #65). HTTPService + WebService — CRUD + full get (E5 / #66). AccountingRegister + CalculationRegister — CRUD + full get (E6 / #67). ChartOfCharacteristicTypes + ChartOfAccounts + ChartOfCalculationTypes — CRUD + full get (E7 / #68). BusinessProcess + Task + ExchangePlan + DocumentJournal — CRUD + full get (E8 / #69). **E-docs (#70):** doctor `supportedTypes`, CLI help, MCP tool descriptions, README / AGENTS — поверхность всех 24 write-типов. **E-accept (#71):** `tests/test_e_acceptance.py` — sample CRUD E0–E8 → build/check (**done**).

Волны (все **done**): [#60](https://github.com/pila86/1c-dev/issues/60) E-found → [#61](https://github.com/pila86/1c-dev/issues/61) E0 → [#62](https://github.com/pila86/1c-dev/issues/62) E1 → [#63](https://github.com/pila86/1c-dev/issues/63)–[#69](https://github.com/pila86/1c-dev/issues/69) E2…E8 → [#70](https://github.com/pila86/1c-dev/issues/70) E-docs → [#71](https://github.com/pila86/1c-dev/issues/71) E-accept.

Out of this track: Role / Form / Command / SessionParameter / …; `xml-gen interface edit` (CommandInterface); полное покрытие платформы ≠ трек E.

## Agent workflows

### A. Реальная конфигурация из `.cf`

> Импортируй configuration.cf, покажи справочники, добавь реквизит.

```
1. project.import(from=configuration.cf, break_support=true)   # типовые на поддержке
2. metadata.list / metadata.find
3. metadata.update / create
4. build / check
```

(При работе из IDE после import — отдельно `ide configure --target …`.)

### B. Онбординг репозитория под агента

> Подготовь этот каталог для работы с 1c-dev в Cursor / Kilocode.

```
1. (user) uv tool install … → 1c-dev в PATH; 1c-dev tools sync
2. ide configure --target cursor   # или kilocode / all
3. doctor
4. агент работает через MCP 1c-dev + bsl-ls; docs.* — по необходимости (lazy index)
```

## Acceptance criteria

### Import

- [x] `1c-dev project import --from <file.cf>` создаёт/обновляет XML source и валидный `1c.project.yaml` (**без** обязательной записи `AGENTS.md` / MCP IDE) — #47
- [x] После import `metadata.list` / `get` видят объекты из `.cf` — #52 (`tests/test_m3_acceptance.py`)
- [x] `build` и `check` после import проходят (или дают платформенные diagnostics) — #52
- [x] Если в `source.path` уже есть `Configuration.xml` и нет `--force` → ошибка с diagnostic, source не затёрт — #47
- [x] MCP: `project.import` без shell.exec — #47
- [x] Integration-тест: `build --artifact cf` → `project.import` (round-trip); skip с сообщением, если нет platform — #47 (`tests/test_project_import.py`)
- [x] should: CLI `runtime load --from <file.cf>` (MCP — later) — #47
- [x] `project import --break-support` удаляет артефакты поддержки (`ParentConfigurations*`) из `source.path` после export; без флага — сохраняет — #74
- [x] Повторный `--break-support` идемпотентен (нет артефактов → ok + diagnostic) — #74
- [x] MCP: `project.import` принимает `break_support` — #74
- [x] Unit-тест: fixture с `ParentConfigurations.bin` → strip без platform — #74
- [x] should: CLI `source break-support` (та же strip-логика без повторного import) — #74
- [x] should: `project clean --yes` удаляет `source.path` и `.runtime/`; без `--yes` — отказ; манифест/IDE intact — ADR-021; #76
- [x] should: MCP `project.clean` с обязательным confirm — #76
- [x] Unit-тест: fixture source + `.runtime` → clean без platform; повторный clean идемпотентен — #76

### Install

- [x] Документированный must-путь: `uv tool install` (git и/или wheel) → `1c-dev` в PATH без Poetry-checkout рядом с продуктом — #45 / README
- [x] `1c-dev tools sync` **автоматически** скачивает в user cache: xml-gen, md-reader (MDClasses), bsl-ls jar, docs-facade — #48
- [x] После `tools sync` на чистой машине (без monorepo) `metadata.create` и `metadata.list`/`get` не требуют ручного `fetch-*.sh` — #48
- [x] Повторный `tools sync` идемпотентен; при смене pin toolchain — обновляет артефакты — #48
- [x] `1c-dev doctor` отражает наличие CLI, **каждого** jar toolchain, Java, platform, ibcmd; отсутствует jar → diagnostic с указанием `tools sync` / `--fix` — #49
- [x] Env-override jar’ов по-прежнему работает — #48 / #49
- [x] README: быстрый старт через `uv tool install` + `1c-dev tools sync` (не только `poetry run` + ручные fetch) — #49

### IDE configure

- [x] `1c-dev ide configure --target cursor|kilocode` пишет/мержит манифест, `AGENTS.md`, MCP-конфиг IDE, `.gitignore` по политике merge выше — #50
- [x] Повторный `ide configure` без `--force` не затирает пользовательские правки (`AGENTS.md` skip; MCP — только недостающие servers; `.gitignore` — append) — #50
- [x] После `ide configure` агент в Cursor (и Kilocode) может вызвать `1c-dev` MCP без ручного копирования репо — #50

### BSL LS + docs

- [x] Doctor / `ide configure` умеют указать рабочий BSL LS MCP (jar в cache или явный путь) — #49 / #50
- [x] В шаблоне IDE MCP — два server’а: `1c-dev` и `bsl-language-server` — #50
- [x] `docs.search` / `docs.get` (CLI + MCP) отвечают по индексу текущей `platform.version` (индекс — lazy при первом вызове) — #51
- [x] Индекс строится через bsl-context из HBK установленной платформы (или skip + diagnostic, если HBK нет) — #51
- [x] AGENTS.md описывает разделение: metadata/build → 1c-dev; BSL-анализ → bsl-ls; API платформы → docs.* — #50 / #51

## Out of scope M3

- EDT adapter / `source.convert` (→ [draft-source-formats](draft-source-formats.md))
- YAxUnit / Vanessa (→ [draft-tests](draft-tests.md))
- DAP, semantic diff, verify против `.cf` как baseline — вне активного roadmap
- Remote runtime / Docker / lockfile / marketplace — вне активного roadmap
- Project home / multi-config / templates / publish (→ [M4](m4-project-model.md))
- `.cf` как постоянный `source.format` в манифесте
- Unified MCP, дублирующий BSL LS tools
- Полный PRD BSL API (`bsl.symbols`, `bsl.definition`, …) внутри 1c-dev
- Vector DB / embeddings для docs
- Публикация на PyPI как must (может быть later / ADR alternative)
- Явный `docs build-index`, `docs.related`, `docs.version`
- MCP для `runtime.load` (CLI — should)
- Must-поддержка «голого» VS Code без Kilocode
- Типы вне xml-gen Meta DSL + Subsystem (Role, Form, Command, SessionParameter, …); `interface edit` / CommandInterface — later (трек E не = «вся платформа»)
- Пообъектные правила поддержки («на замке» / «редактируется»); DESIGNER `/ManageCfgSupport`; штатный vendor-update от поставщика
- `runtime.reset` (только IB) и режим «только runtime» без source — later (не MVP #76)

## Manual verification

```bash
# 0. Install
uv tool install git+https://github.com/pila86/1c-dev
1c-dev --version
1c-dev tools sync --output json       # xml-gen, md-reader/MDClasses, bsl-ls, docs-facade
1c-dev doctor --output json

# 1. Import (типовые: --break-support)
1c-dev project import --from /path/to/configuration.cf --break-support --output json
1c-dev metadata list --output json

# 2. IDE configure
1c-dev ide configure --target cursor --output json
# или: 1c-dev ide configure --target kilocode --output json

# 3. Docs (первый вызов может построить индекс)
1c-dev docs search "Сообщить" --output json
1c-dev docs get "Массив" --output json

# 4. Build / check
1c-dev build --output json
1c-dev check --output json

# 5. Clean (should; destructive)
1c-dev project clean --yes --output json

# 6. M3 acceptance (CF round-trip → list/get → ide configure → docs soft → build/check)
#    skip без platform / xml-gen / md-reader; docs soft без HBK/jar
poetry run pytest tests/test_m3_acceptance.py -m integration

# 7. Track E acceptance (sample E0–E8 create/get/update/delete → build/check)
#    skip без platform / xml-gen / md-reader
poetry run pytest tests/test_e_acceptance.py -m integration
```

## Links

- [GitHub milestone M3](https://github.com/pila86/1c-dev/milestone/3)
- [Roadmap](../roadmap.md)
- [M2](m2-metadata-api.md)
- [M4](m4-project-model.md) · [draft-source-formats](draft-source-formats.md)
- [ADR-001](../adr/001-language-core-cli.md) (packaging → [ADR-013](../adr/013-packaging-toolchain-cache.md))
- [ADR-013](../adr/013-packaging-toolchain-cache.md) (uv tool / cache / pin toolchain)
- [ADR-010](../adr/010-mcp-architecture.md)
- [ADR-018](../adr/018-metadata-types-coverage.md) (трек E: metadata types coverage)
- [ADR-020](../adr/020-break-support.md) (`--break-support` / strip ParentConfigurations*)
- [ADR-021](../adr/021-project-clean.md) (`project.clean` — wipe source + runtime)
- [PRD §20 Documentation API](../../1c-dev-runtime-PRD-v0.1.md), [§19 BSL](../../1c-dev-runtime-PRD-v0.1.md), [§64 bsl-context / BSL LS](../../1c-dev-runtime-PRD-v0.1.md)
- [bsl-context](https://github.com/1c-syntax/bsl-context)
- [BSL LS MCP mode](https://1c-syntax.github.io/bsl-language-server/dev/features/McpMode/)

## Issues

| # | Статус | Задача | Depends on |
|---|--------|--------|------------|
| [#45](https://github.com/pila86/1c-dev/issues/45) | done | ADR: packaging (`uv tool`) / user cache layout + pin toolchain | — |
| [#46](https://github.com/pila86/1c-dev/issues/46) | done | Platform: ibcmd `config load` + `config export` | — |
| [#47](https://github.com/pila86/1c-dev/issues/47) | done | CLI/MCP `project.import` (+ should: CLI `runtime.load`) | #46 |
| [#74](https://github.com/pila86/1c-dev/issues/74) | done | `project.import --break-support` (+ should: `source break-support`); ADR-020 | #47 |
| [#76](https://github.com/pila86/1c-dev/issues/76) | done | should: CLI/MCP `project.clean` (source + `.runtime`); ADR-021 | #47 |
| [#48](https://github.com/pila86/1c-dev/issues/48) | done | `1c-dev tools sync`: bootstrap toolchain jars (+ uninstall) | #45 |
| [#49](https://github.com/pila86/1c-dev/issues/49) | done | Doctor: jar self-checks + `--fix`; README `uv tool` quick start | #48 |
| [#50](https://github.com/pila86/1c-dev/issues/50) | done | CLI `ide configure --target cursor\|kilocode` + merge + MCP/AGENTS templates | #48 |
| [#51](https://github.com/pila86/1c-dev/issues/51) | done | `docs.search` / `docs.get` via bsl-context, lazy index | #48 |
| [#52](https://github.com/pila86/1c-dev/issues/52) | done | Acceptance: E2E import → list/get → ide configure → docs soft → build/check (`tests/test_m3_acceptance.py`) | #47, #50, #51, #74 |
| [#60](https://github.com/pila86/1c-dev/issues/60) | done | **E-found:** Metadata coverage foundation (allowlists, TYPE_DIRS, xml-gen pin, doctor) | — |
| [#61](https://github.com/pila86/1c-dev/issues/61) | done | **E0:** CommonModule full IR get parity | #60 |
| [#62](https://github.com/pila86/1c-dev/issues/62) | done | **E1:** Subsystem create/get/update/delete (priority) | #60, #61 |
| [#63](https://github.com/pila86/1c-dev/issues/63) | done | **E2:** Constant + DefinedType | #60, #62 |
| [#64](https://github.com/pila86/1c-dev/issues/64) | done | **E3:** Report + DataProcessor | #60, #62 |
| [#65](https://github.com/pila86/1c-dev/issues/65) | done | **E4:** ScheduledJob + EventSubscription | #63, #64 |
| [#66](https://github.com/pila86/1c-dev/issues/66) | done | **E5:** HTTPService + WebService | #65 |
| [#67](https://github.com/pila86/1c-dev/issues/67) | done | **E6:** AccountingRegister + CalculationRegister | #66 |
| [#68](https://github.com/pila86/1c-dev/issues/68) | done | **E7:** Charts (CharacteristicTypes / Accounts / CalculationTypes) | #67 |
| [#69](https://github.com/pila86/1c-dev/issues/69) | done | **E8:** BusinessProcess + Task + ExchangePlan + DocumentJournal | #68 |
| [#70](https://github.com/pila86/1c-dev/issues/70) | done | **E-docs:** Doctor/CLI/MCP/README surface новых типов | #69 |
| [#71](https://github.com/pila86/1c-dev/issues/71) | done | **E-accept:** Acceptance E2E 23 meta + Subsystem (`tests/test_e_acceptance.py`) | #61–#70 |
