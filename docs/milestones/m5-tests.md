# M5: Tests (YAxUnit / Vanessa)

**Статус:** Planned — после [M4](m4-project-model.md); [GitHub milestone M5](https://github.com/pila86/1c-dev/milestone/5); контракт зафиксирован ниже, ADR Test API — при старте реализации (Proposed → Accepted).

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
| Где живёт YaXUnit | В **пользовательском** 1С-проекте (test-extension), не в monorepo toolchain | |
| Граница с M4 | Multi-source, extension scaffold, `build`+extension — **M4**; M5 = Test API + тонкий consumer-config | |
| Манифест `tests` | Внутри `configurations[]`; список suites; у suite несколько extensions | См. эскиз ниже |
| Build перед тестами | `test.*` **не** собирает ИБ; агент/CI: `build` → `test.*` | |
| Выбор ИБ | `--runtime` / MCP-аналог; default = default runtime выбранной `--config` | ADR-026 |
| Vanessa | Контракт и место в схеме в M5; `adapters/test_vanessa` — follow-up | Should / carry-over |
| Doctor | Soft gap: предупреждение, остальной CLI не hard-fail | |
| Schema version | `"2"` additive vs bump — **TBD** в ADR / после spike | |
| `test.run` без фильтров при нескольких suites | **TBD** после spike YaXUnit | |

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
      # later / schema-ready:
      # - id: bdd
      #   runner: vanessa
      #   extensions: […]
```

`extensions[]` с `purpose: tests` — модель M4; секция `tests` — тонкая привязка runner ↔ extension ids для Test API (M5).

## Scope

### 1. Spike (must, первый шаг)

- Fixture XML-проект + YaXUnit extension.
- Локально при желании METR (`tools/mcp/`, вне git) — только чтобы понять вызов.
- Результат: понятен `/C RunUnitTests=…` и формат отчёта → заметки в ADR Test API.

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

- `doctor`: capability YaXUnit / runner — **gap**, не hard-fail всего CLI.
- `AGENTS.md`: цикл `build → test.run` перед завершением задачи.
- `ide configure`: **не** подключает METR.

### 5. Vanessa (Should / follow-up)

- Контракт `runner: vanessa` в схеме / API.
- `adapters/test_vanessa/` — не блокирует acceptance YAxUnit-среза; явный carry-over.

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

- [ ] Spike: RunUnitTests + разбор jUnit; заметки для ADR
- [ ] ADR: Test API + граница с METR (own facade)
- [ ] Манифест: валидируемая `configurations[].tests` (suite: `id`, `runner`, `extensions[]`)
- [ ] `1c-dev test` + `discover` / `list` / `run` / `runOne` / `report` → structured JSON (PRD §25–26)
- [ ] Падения тестов → exit code `TEST_FAILURE` (5), ADR-003
- [ ] MCP: `test.discover`, `test.list`, `test.run`, `test.runOne`, `test.report` без shell.exec
- [ ] Выбор ИБ: `--runtime` (default = default runtime `--config`)
- [ ] `doctor` сообщает о наличии/отсутствии runner capability (soft gap)
- [ ] `AGENTS.md`: цикл `build → test.*`
- [ ] Integration-тесты: skip без платформы / YaXUnit, с понятным сообщением

### Should

- [ ] Фильтр suite / модуля (после spike; default multi-suite — TBD)
- [ ] Vanessa: schema/контракт `runner: vanessa`; adapter — follow-up issue
- [ ] Решение schema version (additive `"2"` vs bump) в ADR

### Nice

- [ ] Документировать METR только как «как мы смотрели механику» (не product guide)

## Out of scope

- Multi-source / extension scaffold / `build`+extension — [M4](m4-project-model.md)
- Vendor-in / дистрибуция `mcp-yaxunit-runner.jar` в `tools sync`
- Замена `build` / `check` / `runtime` на METR; companion METR в default DX
- Генерация текста тестов отдельным MCP tool
- Auto-build / incremental build внутри `test.run`
- DAP / debug; Remote / Docker / lockfile
- Собственный unit-test framework вместо YaXUnit
- Реализация `adapters/test_vanessa` (carry-over)

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
| [#129](https://github.com/pila86/1c-dev/issues/129) | 3 | Acceptance: E2E `build → test.run` | #121–#126 |
