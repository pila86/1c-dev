# Draft: write-backend bake-off

**Статус:** Draft (вне roadmap) — подготовка выбора инструмента записи исходников (XML / EDT).  
Связан с [draft-source-formats](draft-source-formats.md) и [ADR-007](../adr/007-metadata-ir.md) (xml-gen).

## Goal

Выбрать стратегию **semantic write** для `source.format: xml` и (отдельно) путь для **`edt`**, зная что `1cedtcli` на EDT-ветке всё равно нужен для `build` (платформа не читает `.mdo`: EDT → export XML → ibcmd).

Не смешивать в одном вердикте: «кто лучше пишет XML» и «как жить с EDT».

## Context

| Слой | Сейчас | Заметка |
|------|--------|---------|
| Read | MDClasses (ADR-012); EDT-ready позже | Не кандидат на write |
| Write XML | xml-gen (ADR-007) | IR → `meta compile` / `edit` / `remove` |
| Write EDT | не выбран | md-sparrow отложен в bake-off 2026-09-17 |
| EDT runtime | draft: нужен `1cedtcli` | export перед build/check |

Аргумент «md-sparrow избавит от EDT CLI» **слаб**: env-cost EDT-ветки уже включает `1cedtcli`. Остаётся асимметрия **export** (build) vs **import** (write через bridge).

## Candidates

| ID | Вариант | Что тестируем |
|----|---------|----------------|
| **A** | **xml-gen** (status quo) | IR → `meta compile/edit/remove` → Designer XML |
| **B** | **md-sparrow** ([yellow-hammer/md-sparrow](https://github.com/yellow-hammer/md-sparrow)) | create/edit/delete → Designer XML; отдельно — есть ли `.mdo` |
| **C** | **xml-gen + 1cedtcli bridge** | write в XML (A), затем `import` в EDT-проект; `build` = `export` → ibcmd |
| **D** (опц.) | **md-sparrow native EDT** | только если B умеет `.mdo`; write в EDT + `export` → ibcmd |

**Вне конкурса:** EDT-MCP / живой EDT IDE, свои XML-шаблоны, MDClasses-as-writer, 1CFilesConverter / vrunner как sole write (только как обёртка convert).

## Environment (зафиксировать до прогона)

- Платформа: как в ADR-007 bake-off или явно (напр. 8.3.27)
- Dump / format version: как после `1c-dev init` / import
- JDK: 17 для A, 21+ для B
- EDT: одна версия + путь к `1cedtcli`
- Fixture: чистый проект после `init` / маленький fixture (не ERP)

## Scenarios

### S1 — Create (повтор ADR-007)

`Catalog.Products`, synonym «Товары», `Article` String(50).

### S2 — Update

Добавить реквизит, ТЧ, поменять synonym; поведение no-op / duplicate.

### S3 — Delete

Удалить объект; состав `Configuration.xml` / ChildObjects корректен.

### S4 — Round-trip platform

После S1–S3: `ibcmd` load/import → apply → `check` (или `1c-dev build` + `check`).

### S5 — IR fit

Один вход: Metadata IR v1 JSON → файлы на диске. Считать шаги CLI, ручной маппинг, потери полей.

### S6 — EDT path (только C/D)

1. Получить EDT-проект с тем же объектом.
2. `1cedtcli export` → XML.
3. `build` / `check` как в [draft-source-formats](draft-source-formats.md).
4. Повторный S1 **уже в EDT-проекте** (второй каталог).

### S7 — EDT claim (только B)

Есть ли документированный/рабочий write в `.mdo`? Если нет — D снимается; в протоколе «B: Designer-only».

## Scoring

| Критерий | Вес | Как мерить |
|----------|-----|------------|
| **Correctness** | must | S4 зелёный; иначе fail |
| **IR proximity** | high | шаги / костыли маппинга IR→tool |
| **EDT story** | high для ветки edt | S6 без ручного шаманства; import/export exit 0 + непустой XML |
| **Ops cost** | med | JDK, размер jar, pin, submodule, cold start |
| **Incremental write** | med | время S1 на существующем проекте; нужен ли full import |
| **Diff noise** | med | git diff после edit (порядок узлов, xmlns, CRLF) |
| **Coverage gap** | med | типы ADR-018 (23 meta + Subsystem) vs факт tool |
| **Risk / bugs** | med | известные fail `1cedtcli import`; нестабильность headless |

**Must-fail:** не грузится в ibcmd; ломает `Configuration.xml`; для C/D — пустой export при exit 0.

## Result log (шаблон)

```text
variant: A|B|C|D
scenario: S1…
command(s): …
wall_time_s: …
exit_code: …
artifacts: paths
ibcmd/check: pass|fail|skip
notes: …
```

### Summary table

| | A xml-gen | B md-sparrow | C bridge | D mdo+export |
|--|:---------:|:------------:|:--------:|:------------:|
| S1 create | | | | |
| S4 platform | | | | |
| S5 IR fit | | | | |
| S6 EDT | n/a | ? | | |
| JDK / jar | 17 / ~7MB | 21–25 / ~24MB | A+EDT | B+EDT |
| Вердикт XML write | | | — | — |
| Вердикт EDT write | — | | | |

## Decisions bake-off must answer

1. **XML write:** оставить **A** или мигрировать на **B**?
2. **EDT write:**
   - **C** (xml-gen + import/convert), или
   - **D** (native `.mdo`), или
   - **отложить create на edt** (только read + convert + export→build)?
3. Нужен ли **второй** write-backend в toolchain или один + bridge?

### Гипотеза до прогона (не вердикт)

- A выигрывает XML по IR/простоте → не трогать xml-gen.
- B без `.mdo` → D вне игры.
- C работает, но хрупко на S6 create → EDT write = convert batch, не каждый `metadata.create`.
- D стабилен → native write + `1cedtcli` только на export.

## Suggested schedule

1. **День 1:** A vs B на S1+S4+S5 (актуальные версии xml-gen / md-sparrow).
2. **День 2:** S7 claim B; если нет `.mdo` — только C: S6 на результате A.
3. **День 3:** вердикт на 1 страницу → ADR (дополнить/заменить следствия ADR-007 + обновить [draft-source-formats](draft-source-formats.md)).

## Links

- [draft-source-formats](draft-source-formats.md)
- [ADR-007](../adr/007-metadata-ir.md) (xml-gen + исторический bake-off с md-sparrow)
- [ADR-012](../adr/012-metadata-read-mdclasses.md) (read; EDT later)
- [ADR-018](../adr/018-metadata-types-coverage.md) (coverage write-типов)
- [Roadmap](../roadmap.md)
- PRD §11–§12 Source Adapter / Source API; §50 contract tests; R1 `1cedtcli`
