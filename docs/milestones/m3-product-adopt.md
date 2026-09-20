# M3: Product adopt (CF import + install + agent setup)

## Goal

Инструмент можно поставить в user cache / PATH **вместе с зависимостями toolchain** (xml-gen, md-reader/MDClasses, …) и начать использовать на **реальной** конфигурации без копирования monorepo: импорт из `.cf`, scaffold IDE/агента в каталоге проекта, подключение BSL LS MCP и локальный индекс знаний о платформе (через bsl-context).

## Prerequisites

- M1 зелёный: `init` → `metadata.create(Catalog)` → `build` → `check`
- M2: Metadata API (list/get/find + update / create beyond Catalog / delete) по XML source
- Платформа 1С 8.3.x, `ibcmd` в PATH (для import / build / check)
- JDK 17+ (xml-gen) и JDK 21+ (md-reader; bsl-context / BSL LS — тоже 21+)

## Scope

Четыре трека. EDT **не** входит (→ [M4](m4-source-formats.md)).

### A. Import из `.cf` (CF → XML source)

Bootstrap существующей конфигурации: бинарный `.cf` → file IB → выгрузка в `source.path`.

`.cf` — **входной** артефакт (не source of truth). Дальше истина — Git + XML source проекта.

Pipeline (ibcmd):

```text
create IB (если нет)
  → config load <file.cf>
  → config apply
  → config export → source.path
```

Публичный контракт:

```bash
1c-dev project import --from configuration.cf
# MCP: project.import
```

Опционально узкий шаг (только CF → IB, без dump в source):

```bash
1c-dev runtime load --from configuration.cf
# MCP: runtime.load
```

Конфликты с уже изменённым `src/` — явный `--force` / отказ с structured diagnostic.

### B. User-level install (cache + PATH + toolchain deps)

Установка CLI **без** `poetry run` и без клонирования репозитория рядом с продуктом. Python-пакет — только оркестратор: **вместе с установкой (или сразу после неё) в user cache должны подтягиваться нативные зависимости toolchain**, сейчас раздаваемые вручную через `scripts/fetch-*.sh`.

Целевой UX:

```bash
# один раз (варианты — зафиксировать ADR)
uv tool install 1c-dev   # или pipx / installer-скрипт
1c-dev install           # или post-install hook / `1c-dev doctor --fix`
1c-dev doctor
```

`1c-dev install` (имя уточнить в ADR) — идемпотентный bootstrap toolchain в user-dir:

| Компонент | Зачем | Примечание |
|-----------|--------|------------|
| **xml-gen** jar | `metadata.create` / `update` | сейчас `scripts/fetch-xml-gen.sh`, JDK 17+ |
| **md-reader** jar (+ **MDClasses** на classpath / shaded) | `metadata.list` / `get` / `find` | сейчас `scripts/fetch-md-reader.sh`, JDK 21+ |
| **bsl-language-server** jar | MCP анализа BSL (трек D1) | скачать release в тот же cache |
| **docs facade** (bsl-context) | `docs.search` / `get` (трек D2) | jar поверх bsl-context; индекс HBK — lazy при первом `docs.*` или явный `docs build-index` |

Ожидания:

- entrypoint `1c-dev` в PATH пользователя
- кэш toolchain в user-dir (например `~/.cache/1c-dev` / `~/.local/share/1c-dev`), с версионированием артефактов (pin / checksum в манифесте toolchain)
- **после install** `metadata.create` / `list` / `get` работают без ручного `./scripts/fetch-*.sh` и без checkout monorepo
- `doctor` проверяет self (CLI, **каждый** jar toolchain, Java, platform, ibcmd) и умеет подсказать / запустить докачку (`--fix` или отсылка к `install`)
- override путей через env (`ONEC_XMLGEN_JAR`, `ONEC_MDREADER_JAR`, …) сохраняется и имеет приоритет над cache
- сеть недоступна / JDK нет → structured diagnostic, CLI при этом остаётся usable для команд без jar

Packaging-решение (`uv tool` / `pipx` / wheel на PyPI / self-contained binary) и layout cache — ADR при старте трека; single-binary не must M3. Maven Central / GitHub Releases как источники jar — reuse текущих fetch-скриптов, но вызов из install, не из README «вручную».

### C. Project setup (манифест + агенты + IDE MCP)

Идемпотентная установка артефактов **в каталог проекта** (существующий Git-репозиторий конфигурации), без копирования monorepo:

```bash
1c-dev setup [--ide cursor|vscode|…] [--force]
# MCP: project.setup (или расширение project.init)
```

Что пишет / мержит (с `--force` и dry-run по желанию):

| Артефакт | Назначение |
|----------|------------|
| `1c.project.yaml` | манифест (если ещё нет; иначе validate / merge минимальных полей) |
| `AGENTS.md` (+ опционально rules/skills) | инструкции агенту: какие MCP/tools звать |
| IDE MCP config (`.cursor/mcp.json`, …) | `1c-dev mcp` + `bsl-language-server mcp` |
| дописывания `.gitignore` | `build/`, `.runtime/`, `.cache/` |

Отличие от `init`: `init` — bootstrap **пустой** конфигурации; `setup` — подключить runtime к **уже существующему** source (после import или clone).

### D. Agent knowledge: BSL LS MCP + docs/context (bsl-context)

Два слоя — не смешивать в один MCP без ADR.

#### D1. BSL Language Server MCP (reuse)

BSL LS уже умеет режим MCP (`java -jar bsl-language-server.jar mcp`). В M3:

- doctor: обнаружить / скачать jar BSL LS в user cache
- `setup --ide …`: прописать отдельный MCP server рядом с `1c-dev`
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

Минимальный публичный контракт:

```bash
1c-dev docs search "ТаблицаЗначений"
1c-dev docs get "Массив.Добавить"
# MCP: docs.search, docs.get
```

Источник знаний для агента: глобальный контекст, типы/методы/свойства, языковые конструкции, при необходимости — элементы языка запросов. Не заливать весь индекс в system prompt — только по запросу tool.

## Agent workflows

### A. Реальная конфигурация из `.cf`

> Импортируй configuration.cf, покажи справочники, добавь реквизит.

```
1. project.import(from=configuration.cf)
2. metadata.list / metadata.find
3. metadata.update / create
4. build / check
```

### B. Онбординг репозитория под агента

> Подготовь этот каталог для работы с 1c-dev в Cursor.

```
1. (user) install 1c-dev в PATH
2. setup --ide cursor
3. doctor
4. агент работает через MCP 1c-dev + bsl-ls; docs.* — по необходимости
```

## Acceptance criteria

### Import

- [ ] `1c-dev project import --from <file.cf>` создаёт/обновляет XML source и валидный `1c.project.yaml`
- [ ] После import `metadata.list` / `get` видят объекты из `.cf`
- [ ] `build` и `check` после import проходят (или дают платформенные diagnostics)
- [ ] Конфликт с dirty source без `--force` → ошибка с diagnostic, source не затёрт
- [ ] MCP: `project.import` без shell.exec
- [ ] Integration-тест: skip с сообщением, если нет platform

### Install

- [ ] Документированный способ поставить `1c-dev` в PATH без Poetry-checkout рядом с продуктом
- [ ] `1c-dev install` (или эквивалент post-install) **автоматически** скачивает в user cache: xml-gen, md-reader (MDClasses), и по scope M3 — bsl-ls jar (+ docs facade, если в треке D)
- [ ] После install на чистой машине (без monorepo) `metadata.create` и `metadata.list`/`get` не требуют ручного `fetch-*.sh`
- [ ] Повторный `install` идемпотентен; при смене pin toolchain — обновляет артефакты
- [ ] `1c-dev doctor` отражает наличие CLI, **каждого** jar toolchain, Java, platform, ibcmd; отсутствует jar → diagnostic с указанием `install` / `--fix`
- [ ] Env-override jar’ов по-прежнему работает
- [ ] README: быстрый старт через установленный CLI (не только `poetry run` + ручные fetch)

### Setup

- [ ] `1c-dev setup` пишет/мержит манифест, `AGENTS.md`, MCP-конфиг IDE, `.gitignore`
- [ ] Повторный `setup` без `--force` не затирает пользовательские правки (или даёт diagnostic)
- [ ] После setup агент в Cursor может вызвать `1c-dev` MCP без ручного копирования репо

### BSL LS + docs

- [ ] Doctor / setup умеют указать рабочий BSL LS MCP (jar в cache или явный путь)
- [ ] В шаблоне IDE MCP — два server’а: `1c-dev` и `bsl-language-server`
- [ ] `docs.search` / `docs.get` (CLI + MCP) отвечают по индексу текущей `platform.version`
- [ ] Индекс строится через bsl-context из HBK установленной платформы (или skip + diagnostic, если HBK нет)
- [ ] AGENTS.md описывает разделение: metadata/build → 1c-dev; BSL-анализ → bsl-ls; API платформы → docs.*

## Out of scope M3

- EDT adapter / `source.convert` (→ [M4](m4-source-formats.md))
- YAxUnit / Vanessa (→ M5)
- DAP, semantic diff, verify против `.cf` как baseline (→ M6)
- Remote runtime / Docker / lockfile / marketplace (→ M7)
- `.cf` как постоянный `source.format` в манифесте
- Unified MCP, дублирующий BSL LS tools
- Полный PRD BSL API (`bsl.symbols`, `bsl.definition`, …) внутри 1c-dev
- Vector DB / embeddings для docs

## Manual verification

```bash
# 0. Install (после ADR packaging)
1c-dev --version
1c-dev install --output json          # xml-gen, md-reader/MDClasses, …
1c-dev doctor --output json

# 1. Import
1c-dev project import --from /path/to/configuration.cf --output json
1c-dev metadata list --output json

# 2. Setup IDE
1c-dev setup --ide cursor --output json

# 3. Docs
1c-dev docs search "Сообщить" --output json
1c-dev docs get "Массив" --output json

# 4. Build / check
1c-dev build --output json
1c-dev check --output json
```

## Links

- [Roadmap](../roadmap.md)
- [M2](m2-metadata-api.md)
- [M4](m4-source-formats.md) (бывший M3 без CF)
- [ADR-001](../adr/001-language-core-cli.md) (packaging было отложено)
- [ADR-010](../adr/010-mcp-architecture.md)
- [PRD §20 Documentation API](../../1c-dev-runtime-PRD-v0.1.md), [§19 BSL](../../1c-dev-runtime-PRD-v0.1.md), [§64 bsl-context / BSL LS](../../1c-dev-runtime-PRD-v0.1.md)
- [bsl-context](https://github.com/1c-syntax/bsl-context)
- [BSL LS MCP mode](https://1c-syntax.github.io/bsl-language-server/features/McpMode/)

## Suggested work packages

| Тема | Зависит от |
|------|------------|
| Platform: `config load` + `config export` (ibcmd) | M1 build/check |
| CLI/MCP `project.import` / `runtime.load` | platform load/export |
| ADR: packaging / user cache layout + pin toolchain deps | — |
| `1c-dev install`: fetch xml-gen, md-reader/MDClasses (reuse `scripts/fetch-*`) | ADR packaging |
| Doctor self-checks по каждому jar + `--fix` → install | `1c-dev install` |
| CLI `setup` + шаблоны IDE MCP / AGENTS | install |
| Fetch/wire BSL LS jar + MCP snippet | setup |
| Java facade над bsl-context + `docs.search`/`get` + cache | doctor platform path |
| Acceptance / integration M3 | import + setup + docs |
