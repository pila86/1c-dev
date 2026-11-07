# ADR-032: EDT Source Adapter + write path D

**Статус:** Accepted  
**Дата:** 2026-11-06

## Контекст

M7 ([m7-source-formats](../milestones/m7-source-formats.md)) требует полный паритет
с XML (**вариант B**): при `source.format: edt` агент использует те же `metadata.*`,
`build`, `check`, а переключение формата — через `source.convert` (PRD §12 / §49 / §50).

Уже зафиксировано:

- XML write — xml-gen ([ADR-007](007-metadata-ir.md)); XML read — MDClasses
  ([ADR-012](012-metadata-read-mdclasses.md)).
- Bake-off 2026-11: EDT write = **D** (md-sparrow native `.mdo` / `apply-mutation` +
  `1cedtcli` export); bridge **C** (xml-gen → `1cedtcli import`) — future / opt-in,
  **не** реализован в M7
  ([write-backend-bakeoff](../spikes/write-backend-bakeoff.md)).
- Spike [#149](https://github.com/pila86/1c-dev/issues/149)
  ([149-edt-source-adapter](../spikes/149-edt-source-adapter.md)): layout EDT,
  discovery `1cedtcli`, export/import smoke, rc 204 / Premature EOF, synonym gap.

Платформа **не** читает `.mdo`: любой `build`/`check` на EDT идёт через
`1cedtcli export` → Designer XML → существующий ibcmd/Designer path
([ADR-008](008-ibcmd-build.md) / [ADR-009](009-ibcmd-check.md) / [ADR-030](030-designer-check-modules.md)).

Нужно заморозить границу EdtSourceAdapter, write path D, convert, doctor capabilities,
diagnostics и имена CLI/MCP — **без** реализации adapter/CLI/MCP в этом ADR
(волны 2–5 M7).

Номер **032** (следующий после ADR-031 Debug).

## Решение

### 1. Scope M7 = полный паритет (B)

| Поверхность | При `source.format: xml` | При `source.format: edt` |
|-------------|--------------------------|---------------------------|
| Agent tools | `metadata.*`, `build`, `check`, `docs.*` | **Те же имена** |
| Semantic write | xml-gen (ADR-007) | **D:** md-sparrow `apply-mutation` → `.mdo` |
| Read → IR v1 | md-reader / MDClasses | Тот же Metadata API; backend — EDT-capable read (#152) |
| Build / check | source XML → ibcmd / Designer | `1cedtcli export` → XML → тот же path |
| Convert | — | `source.convert --to=edt\|xml` |

**Out of scope этого ADR и M7:** публичный `source.write` как замена `metadata.create`;
`source.format: cf`; Remote/Docker/lockfile; Vanessa; DAP `launch.json` (#143).

Статус ADR: **Accepted** после acceptance M7 (#159).

### 2. Контракт Source Adapter (XML vs EDT)

Логический интерфейс PRD §11 сужается до **продуктового** контракта M7.
Публичный semantic write остаётся `metadata.create|update|delete` (не raw `source.write`).

| Capability | XML (сейчас) | EDT (M7 must) | Примечание |
|------------|:------------:|:-------------:|------------|
| detect | layout Designer XML + манифест | `.project` с `V8ConfigurationNature` и/или `src/Configuration/Configuration.mdo` | Spike #149 |
| inspect / info | format + path | format + path + EDT project name | |
| read | MDClasses → IR v1 | MDClasses EDT / эквивалент → IR v1 | #152 |
| create / update / delete | xml-gen | md-sparrow `apply-mutation` (D) | #153 / #154 |
| validate | best-effort / check | то же после export | |
| convert | → edt | → xml | #156 |
| sync pull/push | вне M7 must | вне M7 must | PRD §13 — later |
| incrementalSync | TBD | TBD | PRD §50 |

Манифест (schema `"2"`, уже допускает `format: edt` — [ADR-004](004-project-manifest.md) /
[ADR-022](022-project-home.md)):

```yaml
# configurations[].source / extensions[].source
source:
  format: edt
  path: .            # корень EDT-проекта (.project, DT-INF/, src/)
```

- `source.path` для EDT — **корень EDT-проекта**, не каталог `src/` (в отличие от типичного
  XML `src/cf`).
- Major bump schema **не** нужен.
- Detect без манифеста / расхождение layout ↔ `format` → `PROJECT_ERROR` (2) + diagnostic.

Размещение кода (целевое, волны 2+):

| Слой | Пакет | Роль |
|------|-------|------|
| Discovery `1cedtcli` | `adapters/edtcli/` | уже есть (#149); reuse в doctor/build/convert |
| EDT read / detect | `adapters/source/edt/` (эскиз) | detect + read wiring |
| Write D | `adapters/source/mdsparrow/` (эскиз) | pin jar + `apply-mutation` (#153) |
| Оркестрация | `core/source/`, `core/metadata/`, `core/build/` | выбор adapter по `source.format` |
| CLI / MCP | `cli/source.py`, `mcp_server` | `source convert` / `source.convert` |

### 3. Write path: primary D; bridge C — future / opt-in (не в M7)

```text
metadata.create|update|delete  (source.format: edt)
        │
        ▼
  md-sparrow apply-mutation  ──►  .mdo / Configuration.mdo
        │
        │  (gap / known hole)
        ▼
  1CS010 (warning или hard refuse) — без автоматического fallback
        │
        ┊  future / opt-in (НЕ реализован в M7):
        ┊  bridge C: xml-gen → temp XML → 1cedtcli import
```

| Правило | Решение |
|---------|---------|
| Primary | **D** — native `.mdo` через md-sparrow `apply-mutation` |
| Bridge C | **Future / opt-in** — xml-gen → `1cedtcli import`; **не** реализован в M7; не обещать как текущий fallback в diagnostics |
| Path D gaps | → diagnostic `1CS010` (warning или hard refuse) + contract tests #158; **без** несуществующего auto-fallback C |
| Обычные `cf-*` CLI | Designer-only; **не** write-backend для EDT |
| JDK md-sparrow | Temurin **25+** (bake-off); soft gap в doctor (#151) |
| Pin jar | toolchain cache / `1c-dev tools sync` (#153); override env (эскиз `ONEC_MDSPARROW_JAR`) |
| Synonym / TS gaps | Workaround #154: после `add-md-object` — `cf-md-object-set` (синоним объекта / String length); Number precision и синонимы ТЧ — warning `1CS010`; contract tests #158 |
| Subsystem content | Hard refuse `1CS010` (#165): create с непустым `content` отклоняется целиком (до mutation); `add-content` / `remove-content` — тот же код + suggestion (convert→xml / ручной `<content>` в `.mdo`); upstream [md-sparrow#78](https://github.com/yellow-hammer/md-sparrow/issues/78) |

XML write **не** мигрирует на md-sparrow (ADR-007 / bake-off подтверждён).

### 4. Build / check на EDT

```text
source.format: edt
  → 1cedtcli -data <fresh-tmpdir> -timeout <N> -command export
       --project <abs source.path>
       --configuration-files <scope>/.1c-dev/export/<config-id>/
  → существующий ibcmd import/apply (build)
  → check: file IB после build (ibcmd metadata + Designer /CheckModules; без повторного export)
```

| Правило | Решение |
|---------|---------|
| Workspace | **Всегда** fresh `-data` (tmpdir) на операцию; не шарить bake-off/`_edt-ws-*` |
| Мин. EDT | ≥ **2025.1**; discovery newest под `/opt/1C/1CE/components` (Linux) / Program Files (Windows) |
| Override | `ONEC_EDTCLI` → PATH → newest install (`adapters.edtcli.discover_edtcli`) |
| Export cache | ``.1c-dev/export/<config-id>/`` (пересоздаётся на каждый build); gitignore; `project.clean` удаляет |
| Export «шум» | `[Fatal Error] Premature end of file` при **exit 0** + непустой `Configuration.xml` — **не** fail |
| Пустой export / нет ChildObjects | fail (`1CS007` → `BUILD_FAILURE` в build) |
| rc **204** | project already in workspace → `1CS006` + suggestion fresh `-data` |
| Нет `1cedtcli` | `1CS001` → `ENV_UNAVAILABLE` (3) |
| Compatibility / PMF | Spike: PMF `8.3.24` при dump 2.17 — уточнять при init/convert; не блокирует export smoke |

`check` не зависит от `source.format`: работает по уже собранной file IB после EDT `build` (тот же staging используется только на шаге load). Оркестрация — [#155](https://github.com/pila86/1c-dev/issues/155).

### 5. `source.convert` (CLI + MCP)

| Поверхность | Имя |
|-------------|-----|
| CLI | `1c-dev source convert --to=edt` / `--to=xml` |
| MCP | `source.convert` (thin wrapper, ADR-010; **без** `shell.exec`) |
| Core | `core.source.convert` (эскиз) |

Семантика:

1. XML → EDT: `1cedtcli import` (Designer XML → новый/целевой EDT root) + обновить
   `source.format` / `source.path` в манифесте.
2. EDT → XML: `1cedtcli export` + обновить манифест на `format: xml` и путь выгрузки.
3. Logical project / Metadata IR / agent tool names **не** меняются (PRD §49).
4. После convert тот же flow: `metadata.*` → `build` → `check`.

Опциональный post-import flow (M3):

```bash
1c-dev configuration import --from configuration.cf
1c-dev source convert --to=edt
```

Публичные `source.write` / raw sync — **не** must M7.

### 6. Doctor capabilities (контракт для #151)

Реализация — issue [#151](https://github.com/pila86/1c-dev/issues/151); здесь только контракт.

| Tool / capability | Жёсткость | Смысл |
|-------------------|-----------|--------|
| tool `1cedtcli` / `edtcli` | soft, если нет EDT-проектов; **required** для ops при `format: edt` | discovery как spike |
| capability `edt` (или `source.edt`) | soft gap без бинаря на XML-only машине | наличие CLI ≥2025.1 |
| capability `build` / `check` при edt | требуют `1cedtcli` + `ibcmd` (+ `1cv8` для check) | расширить matrix |
| md-sparrow / JDK 25+ | **soft** warning (`1CD020` / `1CD021`) | нужен для `metadata.*` на edt |
| xml-gen | без изменений для XML; bridge C future | capability `metadata.create|update|delete` в matrix остаётся XML-path (`java`+`xml-gen`); EDT write deps — soft diagnostics, не hard requires |

Doctor **не** hard-fail весь отчёт только из-за отсутствия EDT на машине без `format: edt`.
При работе с EDT-проектом отсутствие `1cedtcli` → `ENV_UNAVAILABLE` (3) на build/convert/metadata write.
Format-aware requires (EDT → `md-sparrow`+JDK 25 вместо xml-gen) — follow-up; сейчас XML path в capability matrix не ломаем.

### 7. Diagnostics и exit codes

Префикс **`1CS…`** (Source / EDT). Префикс `1CE…` **занят** extensions (`1CE001`…) —
не использовать для EDT.

Новый exit code **не** вводить (без amendment [ADR-003](003-diagnostics-exit-codes.md)).

| Ситуация | Code (эскиз) | Exit (ADR-003) |
|----------|--------------|----------------|
| Нет / не найден `1cedtcli` | `1CS001` | `ENV_UNAVAILABLE` (3) |
| EDT < 2025.1 / unsuitable install | `1CS002` | `ENV_UNAVAILABLE` (3) |
| Layout не EDT / detect fail | `1CS003` | `PROJECT_ERROR` (2) |
| `format: edt`, но path не корень проекта | `1CS004` | `PROJECT_ERROR` (2) |
| Export/import rc ≠ 0 (кроме обрабатываемых) | `1CS005` | `RUNTIME_FAILURE` (4) / `BUILD_FAILURE` (6) в build |
| rc 204 workspace collision | `1CS006` | `RUNTIME_FAILURE` (4); suggestion: fresh `-data` |
| Пустой export при exit 0 | `1CS007` | `BUILD_FAILURE` (6) или (4) вне build |
| md-sparrow / JDK недоступен | `1CS008` | `ENV_UNAVAILABLE` (3) |
| Convert: грязный / неоднозначный target | `1CS009` | `PROJECT_ERROR` (2) |
| Path D gap (warning или hard refuse; без bridge C) | `1CS010` | `RUNTIME_FAILURE` (4) на hard refuse; warning при soft gap |
| md-sparrow `apply-mutation` failed / timeout | `1CS011` | `RUNTIME_FAILURE` (4) |

`source` в diagnostics: `"source"` / `"edt"` для product API; `"doctor"` для soft gaps.
MCP: те же `diagnostics[]` в JSON (ADR-010).

Metadata IR ошибки на EDT переиспользуют семейство `1CM…` где семантика та же
(объект не найден, jar missing и т.д.); `1CS…` — про format/CLI/convert/export.

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| Scope B (полный паритет) | Один agent API | Больше волн M7 | **Принято** |
| Scope A (только convert/read) | Меньше работы | Ломает PRD §49 для create | **Отвергнуто** |
| Write D (md-sparrow `.mdo`) | Native; быстрый incremental | JDK 25; synonym gaps | **Принято** (primary) |
| Write C (xml-gen → import) | Reuse xml-gen | Full re-import ~11s; workspace quirks | **Future / opt-in** (не M7) |
| Write только C | Проще pin | Хуже DX/diff/время | **Отвергнуто** как primary |
| Свой `.mdo` writer в Python | Полный контроль | G7; invent bicycle | **Отвергнуто** |
| Префикс `1CE` для EDT | «E = EDT» | Коллизия с extensions | **Отвергнуто** → `1CS` |
| Schema bump `"3"` под edt | Явная major | `format: edt` уже в `"2"` | **Отвергнуто** |
| Новый exit code под EDT | Семантика «source» | Amendment ADR-003 | **Отвергнуто** |
| Шарить `-data` workspace | Быстрее cold start | rc 204; гонки | **Отвергнуто** |

## Последствия

- Волны M7 после этого ADR:
  - [#151](https://github.com/pila86/1c-dev/issues/151) — doctor `edt` / `1cedtcli` / JDK soft;
  - [#152](https://github.com/pila86/1c-dev/issues/152) — `EdtSourceAdapter` detect/read;
  - [#153](https://github.com/pila86/1c-dev/issues/153) — pin md-sparrow + `apply-mutation`;
  - [#154](https://github.com/pila86/1c-dev/issues/154) — `metadata.*` на `format: edt`;
  - [#155](https://github.com/pila86/1c-dev/issues/155) — build/check export path;
  - [#156](https://github.com/pila86/1c-dev/issues/156) / [#157](https://github.com/pila86/1c-dev/issues/157) — convert CLI/MCP;
  - [#158](https://github.com/pila86/1c-dev/issues/158) — contract tests PRD §50;
  - [#159](https://github.com/pila86/1c-dev/issues/159) — acceptance → ADR **Accepted**.
- Обновить capability matrix doctor и schema doctor.tools additive (#151).
- Fixture `tests/fixtures/edt_spike` — канон layout для тестов.
- Закладка ADR-007 / ADR-012: EDT write/read реализуются по этому ADR.

## Связанные решения

- ADR-003 (exit codes), ADR-004 / ADR-022 (manifest `source.format`),
  ADR-005 (doctor), ADR-007 (xml-gen; EDT вне write XML),
  ADR-008 / ADR-009 / ADR-030 (build/check), ADR-010 (MCP),
  ADR-011 / ADR-012 (IR / MDClasses read), ADR-013 (toolchain cache)
- Issue [#150](https://github.com/pila86/1c-dev/issues/150); depends on spike
  [#149](https://github.com/pila86/1c-dev/issues/149)
- [M7](../milestones/m7-source-formats.md),
  spike [149-edt-source-adapter](../spikes/149-edt-source-adapter.md),
  [write-backend-bakeoff](../spikes/write-backend-bakeoff.md)
- PRD §11–§13 Source Adapter/API/Sync, §49 Format switching, §50 Contract tests, R1 `1cedtcli`
