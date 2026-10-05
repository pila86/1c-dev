# M5: Tests (YAxUnit / Vanessa)

**Статус:** Done — acceptance E2E [#129](https://github.com/pila86/1c-dev/issues/129) (`tests/test_m5_acceptance.py`); [GitHub milestone M5](https://github.com/pila86/1c-dev/milestone/5); ADR-029 Accepted. Vanessa adapter — follow-up [#128](https://github.com/pila86/1c-dev/issues/128).

## Goal

Единый Test API в `1c-dev` (CLI + MCP): discover / list / run / runOne / report со structured JSON и exit code `5` при падениях. Backend первого вертикального среза — **YAxUnit**; Vanessa — вторым адаптером тем же контрактом (реализация adapter — follow-up).

Продукт остаётся orchestration layer: **не** свой test framework, **не** замена YaXUnit.

## Prerequisites

- M1–M3 Done: init, metadata, build/check, runtime, ide configure
- **M4 Done (блокер):** multi-config + extensions (`purpose: tests`), `build` загружает configuration и test-extension в ИБ, `runtimes[]`
- Платформа 1С + YaXUnit в тестовом расширении user project
- JDK **не** обязателен для своего runner’а (в отличие от METR jar)

EDT ([draft-source-formats](draft-source-formats.md)) **не** блокер для XML-ветки тестов.

## Decisions

| Тема | Решение | Примечание |
|------|---------|------------|
| Поверхность для агента и CI | **Свой** MCP (`test.*` в `1c-dev mcp`) + CLI `1c-dev test` | ADR-010 thin wrapper, без `shell.exec` |
| METR (`alkoleft/mcp-onec-test-runner`) | Только spike механики / референс; **не** product-путь | GPL; нет non-MCP CLI; пересечение tools с `build`/`check`/`runtime` |
| Где живут тесты и runner | Тесты — в **исходниках** user project (test-extension). Runner YaXUnit `.cfe` — **soft toolchain** в user cache (`tools sync`), подключается неявным `ensure` перед `test run` | ADR-029 §7a; в `project.yaml` / `src/` не пишется |
| Граница с M4 | Multi-source, extension scaffold, `build`+extension — **M4**; M5 = Test API + тонкий consumer-config | |
| Манифест `tests` | Внутри `configurations[]`; список suites; у suite несколько extensions | См. эскиз ниже |
| Build перед тестами | `test.*` **не** собирает ИБ; агент/CI: `build` → `test.*` | Узкий preflight `ensure` (YAXUNIT из cache + safe-mode) — не build; `--no-runner-ensure` |
| Выбор ИБ | `--runtime` / MCP-аналог; default = default runtime выбранной `--config` | ADR-026 |
| Vanessa | Контракт и место в схеме в M5 ([#127](https://github.com/pila86/1c-dev/issues/127)); `adapters/test_vanessa` — follow-up [#128](https://github.com/pila86/1c-dev/issues/128) | Should / carry-over |
| Doctor | Soft gap: предупреждение, остальной CLI не hard-fail | |
| Schema version | `"2"` additive vs bump — **TBD** в ADR / после spike | |
| `test.run` без фильтров при нескольких suites | Все suites выбранной `--config`: `filter.extensions` = объединение `tests[].extensions` (пустой фильтр не оставлять) — [spike #119](../spikes/119-yaxunit-runuittests.md); финал в ADR-029 | |

### Почему не METR как основной MCP

- **GPL-3.0-or-later** — vendor-in JAR в toolchain / дистрибутив без юридической проверки нежелателен.
- **Нет non-MCP CLI** — `Main` поднимает Spring Boot MCP; обернуть JAR из `1c-dev test` для CI нельзя.
- **Пересечение tools** с уже существующими `build` / `check` / `runtime.*` / syntax — два оркестратора путают агента.
- Принципы: agent-independent, один контракт CLI+MCP, reuse runner’ов через **adapter**, не через второй product MCP.

Референс механики YaXUnit (из METR / YaXUnit):  
`1cv8 ENTERPRISE … /C RunUnitTests=<json-config>` → jUnit-отчёт → парсинг в structured JSON.

## Эскиз манифеста (consumer-config)

```yaml
configurations:
  - id: main
    type: configuration
    default: true
    source: { format: xml, path: src/cf }
    extensions:
      - id: test-ext1
        name: Tests1
        purpose: tests
        source: { format: xml, path: src/cfe/test-ext1 }
      - id: test-ext2
        name: Tests2
        purpose: tests
        source: { format: xml, path: src/cfe/test-ext2 }
    tests:
      - id: unit
        runner: yaxunit
        extensions: [test-ext1, test-ext2]
      # schema-ready (#127); adapter — #128:
      # - id: bdd
      #   runner: vanessa
      #   extensions: […]
```

`extensions[]` с `purpose: tests` — модель M4; секция `tests` — тонкая привязка runner ↔ extension ids для Test API (M5).

## Scope

### 1. Spike (must, первый шаг)

- Fixture XML-проект + YaXUnit extension.
- Локально при желании METR (`tools/mcp/`, вне git) — только чтобы понять вызов.
- Результат: понятен `/C RunUnitTests=…` и формат отчёта → заметки в ADR Test API: [docs/spikes/119-yaxunit-runuittests.md](../spikes/119-yaxunit-runuittests.md), fixture — [tests/fixtures/yaxunit_spike/](../../tests/fixtures/yaxunit_spike/README.md).

### 2. Манифест `configurations[].tests`

- Валидируемая секция suites: `id`, `runner`, `extensions[]`.
- Версия schema (additive `"2"` vs bump) — TBD в ADR.

### 3. Test API (PRD §25–26)

```text
CLI:  1c-dev test | test list | test run | test run <name> | …
Core: core/test/
Adapter: adapters/test_yaxunit/   # subprocess 1cv8 + jUnit → JSON
MCP:  test.discover, test.list, test.run, test.runOne, test.report
```

Must: полный набор PRD. Фильтры suite / runtime — CLI/MCP флаги (`--config`, `--runtime`, suite — уточнить после spike).

### 4. Doctor / DX

- `doctor`: capability `test.yaxunit` (cache `yaxunit.cfe` + `1cv8` + `ibcmd`) — **soft gap**, не hard-fail всего CLI.
- Runner cache + ensure: `tools sync` → `yaxunit.cfe`; `1c-dev yaxunit ensure`; implicit ensure в `test run` ([ADR-029 §7a](../adr/029-test-api.md)).
- `AGENTS.md`: цикл `build → test.run` перед завершением задачи.
- `ide configure`: **не** подключает METR.

### 5. Vanessa (Should / follow-up)

- Контракт `runner: vanessa` в схеме / API — [#127](https://github.com/pila86/1c-dev/issues/127).
- `adapters/test_vanessa/` — не блокирует acceptance YAxUnit-среза; carry-over
  [#128](https://github.com/pila86/1c-dev/issues/128).

## Фазы внедрения

| Фаза | Содержание | Результат |
|------|------------|-----------|
| **0. Spike** | Fixture + YaXUnit; optional METR локально | Вызов RunUnitTests + формат отчёта; заметки → ADR |
| **1. ADR + schema** | ADR Test API / граница METR; `configurations[].tests` | Зафиксирован контракт и валидация |
| **2. Test API** | `adapters/test_yaxunit` + CLI + JSON + exit 5 | CI-friendly `1c-dev test run` |
| **3. MCP + DX** | `test.*` в `1c-dev mcp`, AGENTS, doctor | Агент гоняет тесты без чужого MCP |
| **4. Vanessa** | Второй adapter (follow-up) | BDD path из PRD |

## Agent workflow (целевой)

```text
AI читает BSL
  → пишет/правит тесты YaXUnit (текст — AI, не generate_test MCP)
  → build
  → test.run (свой MCP)
  → structured result
  → правки
```

## Acceptance criteria

### Must (YAxUnit vertical slice)

- [x] Spike: RunUnitTests + разбор jUnit; заметки для ADR ([#119](../spikes/119-yaxunit-runuittests.md))
- [x] ADR: Test API + граница с METR (own facade) — [ADR-029](../adr/029-test-api.md) Accepted
- [x] Манифест: валидируемая `configurations[].tests` (suite: `id`, `runner`, `extensions[]`)
- [x] `1c-dev test` + `discover` / `list` / `run` / `runOne` / `report` → structured JSON (PRD §25–26)
- [x] Падения тестов → exit code `TEST_FAILURE` (5), ADR-003
- [x] MCP: `test.discover`, `test.list`, `test.run`, `test.runOne`, `test.report` без shell.exec
- [x] Выбор ИБ: `--runtime` (default = default runtime `--config`)
- [x] YaXUnit `.cfe` в user cache (`tools sync`, `ONEC_YAXUNIT_CFE`) + implicit `ensure` перед `test run` и `1c-dev yaxunit ensure` (ADR-029 §7a)
- [x] `doctor` сообщает о наличии/отсутствии runner capability (soft gap)
- [x] `AGENTS.md`: цикл `build → test.*`
- [x] Integration-тесты: skip без платформы / YaXUnit, с понятным сообщением (`tests/test_m5_acceptance.py`, #129)

### Should

- [x] Фильтр suite / модуля (`--suite`, `runOne` / `Module.Method[.Context]`; multi-suite default — ADR-029)
- [x] Vanessa: schema/контракт `runner: vanessa` ([#127](https://github.com/pila86/1c-dev/issues/127)); adapter — follow-up [#128](https://github.com/pila86/1c-dev/issues/128)
- [x] Решение schema version (additive `"2"` vs bump) в ADR-029

### Nice

- [ ] Документировать METR только как «как мы смотрели механику» (не product guide)

## Out of scope

- Multi-source / extension scaffold / `build`+extension — [M4](m4-project-model.md)
- Vendor-in / дистрибуция `mcp-yaxunit-runner.jar` (METR) в `tools sync` (YaXUnit `.cfe` из Apache-2.0 релиза — наоборот, в scope, ADR-029 §7a)
- Замена `build` / `check` / `runtime` на METR; companion METR в default DX
- Генерация текста тестов отдельным MCP tool
- Auto-build / incremental build внутри `test.run`
- DAP / debug; Remote / Docker / lockfile
- Собственный unit-test framework вместо YaXUnit
- Реализация `adapters/test_vanessa` (carry-over [#128](https://github.com/pila86/1c-dev/issues/128))

## Manual verification (эскиз)

```bash
# в user project с YaXUnit extension(s) и configurations[].tests
1c-dev build --output json
1c-dev test list --output json
1c-dev test run --output json
# MCP: test.discover / test.run / test.report
```

## Links

- [GitHub milestone M5](https://github.com/pila86/1c-dev/milestone/5)
- [Roadmap](../roadmap.md)
- [PRD §25 Test API](../../1c-dev-runtime-PRD-v0.1.md), [§26 Test Result](../../1c-dev-runtime-PRD-v0.1.md)
- [ADR-003](../adr/003-diagnostics-exit-codes.md) (exit 5), [ADR-010](../adr/010-mcp-architecture.md), [ADR-023](../adr/023-multi-config-extensions.md), [ADR-026](../adr/026-runtimes-array.md)
- [M3](m3-product-adopt.md), [M4](m4-project-model.md), [draft-source-formats](draft-source-formats.md)
- Внешние: [bia-technologies/yaxunit](https://github.com/bia-technologies/yaxunit), [alkoleft/mcp-onec-test-runner](https://github.com/alkoleft/mcp-onec-test-runner) (референс / spike only)

## Issues

[GitHub milestone M5](https://github.com/pila86/1c-dev/milestone/5). Волны: **0** spike → **1** ADR + schema → **2** adapter + core + CLI → **3** MCP + DX + acceptance.

| # | Wave | Задача | Depends on |
|---|------|--------|------------|
| [#119](https://github.com/pila86/1c-dev/issues/119) | 0 | Spike: YaXUnit `RunUnitTests` + jUnit (fixture, формат отчёта) | M4 Done |
| [#120](https://github.com/pila86/1c-dev/issues/120) | 1 | ADR-029: Test API и граница с METR | #119 |
| [#121](https://github.com/pila86/1c-dev/issues/121) | 1 | Манифест: валидируемая `configurations[].tests` | #120 |
| [#122](https://github.com/pila86/1c-dev/issues/122) | 2 | `adapters/test_yaxunit`: RunUnitTests + разбор jUnit | #119, #120 |
| [#123](https://github.com/pila86/1c-dev/issues/123) | 2 | `core/test`: discover / list / run / runOne / report | #121, #122 |
| [#124](https://github.com/pila86/1c-dev/issues/124) | 2 | CLI `1c-dev test` + exit 5 | #123 |
| [#125](https://github.com/pila86/1c-dev/issues/125) | 3 | MCP `test.*` | #123 |
| [#126](https://github.com/pila86/1c-dev/issues/126) | 3 | Doctor capability YaXUnit + AGENTS: `build → test.*` | #122, #125 |
| [#127](https://github.com/pila86/1c-dev/issues/127) | 3 | should: контракт `runner: vanessa` (без adapter) | #121 |
| [#128](https://github.com/pila86/1c-dev/issues/128) | follow-up | `adapters/test_vanessa` (carry-over) | #127, #124 |
| — | 3 | Runner cache + `ensure`: toolchain `yaxunit`, `core/test/runner_ensure.py`, `1c-dev yaxunit ensure`, doctor `test.yaxunit` (ADR-029 §7a) | #122, #124 |
| [#129](https://github.com/pila86/1c-dev/issues/129) | 3 | Acceptance: E2E `tools sync → build → test.run` (без ручного `extension add YAXUNIT`) | #121–#126 |
