# M5: Tests (YAxUnit / Vanessa)

**Статус:** Draft (черновик стратегии, реализация не начата)

## Goal

Единый Test API в `1c-dev` (CLI + MCP): discover / list / run с structured JSON и exit code `5` при падениях. Backend первого вертикального среза — **YAxUnit**; Vanessa — вторым адаптером тем же контрактом.

Продукт остаётся orchestration layer: **не** свой test framework, **не** замена YaXUnit.

## Ключевое решение (draft)

| Тема | Решение |
|------|---------|
| Поверхность для агента и CI | **Свой** MCP (`test.*` в `1c-dev mcp`) + CLI `1c-dev test` |
| METR (`alkoleft/mcp-onec-test-runner`) | **Не** продукт-путь: только spike механики и опциональный companion MCP |
| Где живёт YaXUnit | В **пользовательском** 1С-проекте (тестовое расширение), не в monorepo toolchain |
| Тесты monorepo `tests/` | По-прежнему pytest toolchain; YaXUnit — integration skip без платформы |

### Почему не METR как основной MCP

- **GPL-3.0-or-later** — vendor-in JAR в toolchain / дистрибутив без юридической проверки нежелателен; «скачай сам» как optional — допустимо.
- **Нет non-MCP CLI** — `Main` поднимает Spring Boot MCP; обернуть JAR из `1c-dev test` для CI нельзя.
- **Пересечение tools** с уже существующими `build` / `check` / `runtime.*` / syntax — два оркестратора путают агента.
- Принципы: agent-independent, один контракт CLI+MCP, reuse runner’ов через **adapter**, не через второй product MCP.

Референс механики YaXUnit (из METR / YaXUnit):  
`1cv8 ENTERPRISE … /C RunUnitTests=<json-config>` → jUnit-отчёт → парсинг в structured JSON.

При старте реализации зафиксировать отдельным ADR (Proposed → Accepted).

## Prerequisites

- M1–M2: init, metadata, build, check
- M3: file IB, `runtime.*`, `ide configure` (шаблон MCP без test-runner)
- Модель **расширений** / multi-source в манифесте (сейчас один `source.path`, init только `configuration`) — блокер или первый трек M5
- Платформа 1С + YaXUnit в тестовом расширении user project
- JDK не обязателен для своего runner’а (в отличие от METR jar)

M4 (EDT) **не** блокер для XML-ветки M5; EDT + tests — после/параллельно M4 при необходимости.

## Scope

### 1. Модель проекта

- Углубить секцию `tests` в `1c.project.yaml` (сейчас shallow optional, ADR-004).
- Multi-source / test extension: основная конфигурация + extension с purpose tests / YaXUnit.
- Scaffold: `templates/` для test-extension и/или `1c-dev test init`.
- `build` загружает configuration **и** test-extension в ту же file IB.

Эскиз манифеста:

```yaml
tests:
  unit:
    runner: yaxunit
    path: tests/unit          # или путь к расширению
    # extension / source-set — уточнить в ADR
```

### 2. Test API (PRD §25–26)

```text
CLI:  1c-dev test | test list | test run | test run <name>
Core: core/test/
Adapter: adapters/test_yaxunit/   # subprocess 1cv8 + jUnit → JSON
MCP:  test.list, test.run, …      # thin wrapper (ADR-010), без shell.exec
```

Дополнительно по PRD (можно later в том же milestone): `test.discover`, `test.runOne`, `test.report`.

### 3. Doctor / DX

- `doctor`: capability YaXUnit / runner (gap, не hard-fail всего CLI).
- `AGENTS.md`: цикл `build → test.run` перед завершением задачи.
- `ide configure`: **не** обязан подключать METR; опциональный advanced-путь — отдельно, если понадобится.

### 4. Vanessa (второй срез)

- `adapters/test_vanessa/` под тем же `test.*`.
- Не блокирует acceptance первого среза (YAxUnit only).

## Фазы внедрения

| Фаза | Содержание | Результат |
|------|------------|-----------|
| **0. Spike** | Fixture XML-проект + YaXUnit extension; при желании локально METR (`tools/mcp/`, вне git) | Понятен вызов `/C RunUnitTests=…` и формат отчёта; заметки → ADR |
| **1. Project model** | Multi-source / extension + `tests` schema + scaffold + build с extension | Есть куда вешать runner |
| **2. Test API** | `adapters/test_yaxunit` + CLI + JSON + exit 5 | CI-friendly `1c-dev test run` |
| **3. MCP + DX** | `test.*` в `1c-dev mcp`, AGENTS, doctor | Агент гоняет тесты без чужого MCP |
| **4. Vanessa** | Второй adapter | BDD path из PRD |

Пока M3 не закрыт — **не** раздувать `ide configure` продуктовым METR.

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

- [ ] ADR: Test API + граница с METR (own facade)
- [ ] Манифест: валидируемая секция `tests` + поддержка test extension / multi-source
- [ ] Scaffold тестового расширения с YaXUnit (init или `test init`)
- [ ] `build` применяет config + test extension в file IB
- [ ] `1c-dev test list` / `test run` → structured JSON (PRD §26)
- [ ] Падения тестов → exit code `TEST_FAILURE` (5), ADR-003
- [ ] MCP: `test.list`, `test.run` без shell.exec
- [ ] `doctor` сообщает о наличии/отсутствии runner capability
- [ ] Integration-тесты: skip без платформы / YaXUnit, с понятным сообщением

### Should

- [ ] `test.run <name>` / фильтр модуля
- [ ] Опциональная документация: METR как companion (не в default `ide configure`)
- [ ] Vanessa adapter (или явный carry-over в follow-up issue)

### Nice

- [ ] Инкрементальная сборка перед тестами (как идея METR) — только если не ломает простой pipeline

## Out of scope M5

- Vendor-in / дистрибуция `mcp-yaxunit-runner.jar` в `tools sync`
- Замена `build` / `check` / `runtime` на METR
- Генерация текста тестов отдельным MCP tool
- DAP / debug (→ M6)
- Remote runtime / Docker / lockfile (→ M7)
- Собственный unit-test framework вместо YaXUnit

## Manual verification (эскиз)

```bash
# в user project с YaXUnit extension
1c-dev build --output json
1c-dev test list --output json
1c-dev test run --output json
# MCP: test.run
```

## Связь с выжимкой коллег (METR)

Коллеги описали ручное подключение METR к AI-клиенту (`application.yml`, `stdio`, `run_all_tests`). Это валидный **локальный** сценарий для уже готового 1С-проекта, но **не** стратегия продукта `1c-dev`.

Использовать из той выжимки:

- идею `source-set` (MAIN + TESTS/YAXUNIT) → отразить в манифесте;
- checklist окружения (JDK для METR-spike, платформа, расширение, ИБ);
- `.gitignore` для локального JAR / секретов в `application.yml`, если кто-то поднимает METR рядом.

Не переносить в default DX:

- второй полный MCP с `build_project` / `check_syntax_*` / `launch_app`;
- обязательный `tools/mcp/mcp-yaxunit-runner.jar` в репозитории пользователя через наш `ide configure`.

## Links

- [Roadmap](../roadmap.md)
- [PRD §25 Test API](../../1c-dev-runtime-PRD-v0.1.md), [§26 Test Result](../../1c-dev-runtime-PRD-v0.1.md), [§8 manifest tests](../../1c-dev-runtime-PRD-v0.1.md)
- [ADR-003](../adr/003-diagnostics-exit-codes.md) (exit 5), [ADR-004](../adr/004-project-manifest.md), [ADR-010](../adr/010-mcp-architecture.md)
- [M3](m3-product-adopt.md), [M4](m4-source-formats.md)
- Внешние: [bia-technologies/yaxunit](https://github.com/bia-technologies/yaxunit), [alkoleft/mcp-onec-test-runner](https://github.com/alkoleft/mcp-onec-test-runner) (референс / spike only)

## Suggested work packages

| Тема | Зависит от |
|------|------------|
| Spike: RunUnitTests + jUnit parse (+ optional METR) | платформа, fixture |
| ADR Test API / граница METR | spike |
| Multi-source / test extension + schema `tests` | ADR-004 bump / additive |
| Scaffold test extension | multi-source |
| `build` + extension | scaffold |
| `adapters/test_yaxunit` + CLI | build + spike |
| MCP `test.*` + AGENTS + doctor | CLI зелёный |
| Vanessa adapter | тот же Test API |
