# ADR-029: Test API и граница с METR

**Статус:** Accepted  
**Дата:** 2026-10-05

## Контекст

M5 ([m5-tests.md](../milestones/m5-tests.md)) требует единый Test API (CLI + MCP) поверх YaXUnit
в user project: discover / list / run / runOne / report, structured JSON, exit code `5`
при падениях (ADR-003). Spike [#119](https://github.com/pila86/1c-dev/issues/119)
([docs/spikes/119-yaxunit-runuittests.md](../spikes/119-yaxunit-runuittests.md))
зафиксировал механику `1cv8 … /CRunUnitTests=<json>` → jUnit → разбор результата.

Внешний референс — [alkoleft/mcp-onec-test-runner](https://github.com/alkoleft/mcp-onec-test-runner)
(METR): тот же вызов YaXUnit, но GPL-3.0-or-later, только MCP (Spring Boot `Main`,
без non-MCP CLI), пересечение tools с уже существующими `build` / `check` / `runtime.*`.
Нужно явно зафиксировать: свой facade в `1c-dev`, METR — не product-путь.

Открытые TBD из M5 / spike: schema version для `configurations[].tests`,
default multi-suite filter, семантика discover/list без native dry-run YaXUnit,
выбор runner-extension `YAXUNIT`, exit codes при «0 тестов» и ошибках запуска.

## Решение

### 1. Свой Test API facade (не METR)

| Поверхность | Контракт |
|-------------|----------|
| CLI | `1c-dev test` / `test list` / `test run` / `test run <name>` / `test report` … |
| Core | `core/test/` — оркестрация, фильтры, JSON result |
| Adapter | `adapters/test_yaxunit/` — subprocess `1cv8` + jUnit → structured JSON |
| MCP | `test.discover`, `test.list`, `test.run`, `test.runOne`, `test.report` в `1c-dev mcp` |

- Продукт — **orchestration layer**: не свой test framework, не замена YaXUnit.
- MCP — thin wrapper над `core/test` (ADR-010): без `shell.exec`, без парсинга CLI stdout.
- Vanessa: тот же контракт (`runner: vanessa` в схеме/API); `adapters/test_vanessa/` — follow-up
  ([#127](https://github.com/pila86/1c-dev/issues/127) / [#128](https://github.com/pila86/1c-dev/issues/128)).
- YaXUnit живёт в **пользовательском** проекте (test-extension), не в monorepo toolchain.
- `ide configure` **не** подключает METR; JDK для runner’а не обязателен.

**METR** — только spike / референс механики. Не vendor-in JAR, не companion MCP в default DX,
не замена `build` / `check` / `runtime`.

### 2. Граница с M4 и build

- Multi-source, extension scaffold, `build`+extension — **M4** (ADR-023 / ADR-026).
- M5 = Test API + тонкая секция `configurations[].tests` (consumer-config).
- `test.*` **не** собирает ИБ. Цикл агента/CI: `build` → `test.*`.
- Auto-build / incremental внутри `test.run` — out of scope.

### 3. Манифест `configurations[].tests` и schema version

Секция suites внутри выбранной configuration (эскиз M5):

```yaml
configurations:
  - id: main
    # …
    extensions:
      - id: yaxunit
        name: YAXUNIT
        purpose: tests
        source: { format: xml, path: src/cfe/yaxunit }
      - id: test_ext1
        name: Tests1
        purpose: tests
        source: { format: xml, path: src/cfe/test_ext1 }
    tests:
      - id: unit
        runner: yaxunit
        extensions: [test_ext1]   # manifest id; имена для YaXUnit — из extensions[].name
```

| Поле suite | Обязательно | Смысл |
|------------|-------------|--------|
| `id` | да | id suite для `--suite` / MCP |
| `runner` | да | `yaxunit` \| `vanessa` (vanessa — контракт; adapter later) |
| `extensions` | да, непустой | id из `extensions[]` с тестовыми модулями (**не** включать `YAXUNIT`) |

**Schema version:** additive внутри schema **`"2"`** — необязательная `configurations[].tests`.
Не требует bump major и не ломает проекты M4 без секции. Bump — только если #121 введёт
несовместимые изменения верхнего уровня (не ожидается).

**Терминология (обязательная в API/доках):**

| Термин | Значение |
|--------|----------|
| `testSuite` / suite манифеста | элемент `configurations[].tests[]` |
| `testSet` / group | тестовый набор YaXUnit (`ДобавитьТестовыйНабор`) |
| `extension` в результате | имя extension (`extensions[].name` ↔ jUnit `testsuite@package`) |

### 4. Операции API (PRD §25–26)

| Операция | CLI (эскиз) | MCP | Семантика v1 |
|----------|-------------|-----|--------------|
| discover | `1c-dev test discover` | `test.discover` | Статика: suites / extensions / модули с экспортной `ИсполняемыеСценарии` из source `purpose: tests` (без платформы) |
| list | `1c-dev test list` | `test.list` | Лучший доступный список тестов: из **последнего** `report` и/или best-effort parse; на чистом проекте может быть неполным |
| run | `1c-dev test run` | `test.run` | Прогон выбранных suites → structured JSON |
| runOne | `1c-dev test run <name>` | `test.runOne` | Один тест: `Module.Method[.Context]` → YaXUnit `filter.tests` |
| report | `1c-dev test report` | `test.report` | Последний сохранённый отчёт / артефакт прогона |

**Discover/list:** у YaXUnit 25.12 нет dry-run «список без выполнения» → вариант **C** spike §6
(не полный прогон как inventory, не обещать точный list без `run`).

### 5. Выбор configuration / runtime / suite

- `--config` / MCP `config_id` — configuration (ADR-023); default = `default: true` / единственная.
- `--runtime` / MCP `runtime_id` — ИБ (ADR-026); default = default runtime выбранной `--config`
  (если у config одна ИБ и runtime не указан — выбрать её).
- `--suite <id>` — один manifest suite; без флага — **все** suites выбранной config (см. §6).
- Параллельные прогоны на одной file IB — **не** поддерживать в v1.

### 6. Default multi-suite и фильтры YaXUnit

Без `filter.extensions` YaXUnit обходит **все** общие модули всех extension → побочные эффекты
и чужие тесты. Продукт **всегда** задаёт явный `filter.extensions`.

1. `test.run` без `--suite` = все suites выбранной `--config`:
   `filter.extensions = ⋃ tests[].extensions` (имена из `extensions[].name`, **без** `YAXUNIT`).
2. `--suite <id>` → `filter.extensions = tests[id].extensions` (имена).
3. `--module` / `runOne` → `filter.modules` / `filter.tests` **вместе с** `filter.extensions`
   своего suite. При неоднозначности имён модулей между extension — требовать `--suite`.
4. Один процесс `1cv8` на один `test.run` (suites объединяются в один `filter.extensions`).
5. **Runner-extension:** extension с `purpose: tests`, чей `id` **не** входит ни в один
   `tests[].extensions` (типично `name: YAXUNIT`). Должен быть загружен в ИБ через `build`;
   в `filter.extensions` **не** попадает. Явное поле манифеста под runner — не вводится в v1.

Валидация до запуска: путь `runOne` / `filter.tests` = `Module.Method[.Context]`
(иначе hang YaXUnit — spike §4).

### 7. Adapter `test_yaxunit` (контракт вызова)

Канон из spike (YaXUnit ≥ 25.09 для `;key=value`, базовый `=<json>` — старше):

```text
1cv8 ENTERPRISE /F<abs ib>
  /DisableStartupDialogs /DisableStartupMessages /DisableSplash
  /L ru /Out <out.log>
  "/CRunUnitTests=<abs cfg.json>"
```

Обязательные поля JSON-конфига: `reportFormat: "jUnit"`, абсолютный `reportPath`,
`closeAfterTests: true`, `showReport: false`, путь `exitCode` (файл), `logging.file`,
явный `filter`. Формат `JSON` в YaXUnit 25.12 не поддерживается — только jUnit (или allure later).

**Pre-flight / runtime wiring (ответственность adapter + core):**

- нужен X-сервер (`DISPLAY`); fallback headless — `xvfb-run -a` (иначе exit 255 → `ENV_UNAVAILABLE`);
- у test-extension и `YAXUNIT` — `safe-mode=no` / `unsafe-action-protection=no`
  (`ibcmd extension update`, абсолютные пути) до прогона;
- обязательный timeout; при timeout — kill **process group** (`start_new_session` / `killpg`).

Подготовка ИБ (import/apply) — зона `build` (M4); отключение safe-mode — pre-flight `test.*`
или follow-up на `build` для `purpose: tests` (реализация — issues adapter/core, не этот ADR).

### 8. Test Result JSON и exit codes

Маппинг jUnit → structured result (вход для PRD §26):

| jUnit | JSON |
|-------|------|
| `testsuite@package` | `extension` |
| `testsuite@classname` | `module` |
| `testsuite@name` / `@context` | `testSet` + `context` |
| `testcase@name` | `test`; id для runOne: `Module.Method[.Context]` |
| нет child / `<failure>` / `<error>` / `<skipped>` | `passed` / `failed` / `error` / `skipped` |
| агрегаты + `time` | `passed`/`failed`/… counts, `durationSec` |

- Агенту: `message` + усечённый `details` (полный стек — `--verbose` / отдельный артефакт).
- Процесс `1cv8` при падении тестов часто возвращает **0**; источник истины — jUnit и/или файл `exitCode` (`0`/`1`, UTF-8 с BOM).

| Ситуация | Exit CLI | Константа (ADR-003) |
|----------|----------|---------------------|
| Все тесты passed (и `total > 0`) | 0 | `SUCCESS` |
| Есть `failed` или `error` | **5** | `TEST_FAILURE` |
| `skipped` без failed/error | 0 | `SUCCESS` |
| Отчёт есть, `total == 0` | **1** | `CHECK_FAILURE` (пустой прогон = ошибка фильтра/конфига, не «успех») |
| Нет отчёта / hang / timeout / ошибка компиляции модуля | 4 (или 3 при нет DISPLAY/платформы) | `RUNTIME_FAILURE` / `ENV_UNAVAILABLE` |
| Нет `configurations[].tests` / битый манифест | 2 | `PROJECT_ERROR` |

MCP: те же статусы и `diagnostics[]` в JSON; exit codes CLI на MCP не маппятся (ADR-010).

### 9. Doctor / DX (контракт, не реализация здесь)

- `doctor`: capability YaXUnit / test runner — **soft gap**, не hard-fail остального CLI.
- `AGENTS.md`: цикл `build → test.*` перед завершением задачи (issue DX).
- Integration-тесты: skip без платформы / YaXUnit с понятным сообщением.

## Альтернативы

| Вариант | Плюсы | Минусы | Вердикт |
|---------|-------|--------|---------|
| Свой CLI+MCP facade + adapter YaXUnit | Один контракт; CI без GPL; reuse ADR-010 | Свой код парсинга jUnit | **Принято** |
| METR как product MCP / vendor-in JAR | Меньше кода runner | GPL; нет CLI; пересечение tools | **Отвергнуто** |
| Обертка `1c-dev test` → METR JAR | Быстрый spike | Нет non-MCP Main; лицензия | **Отвергнуто** |
| Schema bump `"3"` под `tests` | Явная major | Ломает M4 без нужды | **Отвергнуто** (additive `"2"`) |
| Discover = полный прогон | Точный список | Побочные эффекты; не list | **Отвергнуто** для v1 |
| Пустой `filter.extensions` «как YaXUnit default» | Меньше кода | Чужие модули/тесты | **Отвергнуто** |
| `total==0` → exit 0 | Совпадает с YaXUnit rc | Ложные green в CI | **Отвергнуто** (`CHECK_FAILURE`) |

## Последствия

- Реализация: [#121](https://github.com/pila86/1c-dev/issues/121) schema/validate `tests[]`;
  [#122](https://github.com/pila86/1c-dev/issues/122) adapter; [#123](https://github.com/pila86/1c-dev/issues/123) core;
  [#124](https://github.com/pila86/1c-dev/issues/124) CLI+exit 5; [#125](https://github.com/pila86/1c-dev/issues/125) MCP;
  [#126](https://github.com/pila86/1c-dev/issues/126) doctor/AGENTS.
- Документировать METR только как «механика spike», не product guide (Nice M5).
- Известные gaps вне Test API (follow-up M4/M5): bug шаблона `Languages/Русский.xml.tmpl`
  (`ExtendedConfigurationObject`); нормализация id `test-ext1` → `test_ext1`; safe-mode
  не снимается текущим `build` — см. spike §8.

## Связанные решения

- ADR-003 (exit 5), ADR-010 (MCP thin wrapper), ADR-023 (multi-config / extensions),
  ADR-026 (`runtimes[]`)
- Issue [#120](https://github.com/pila86/1c-dev/issues/120); depends on spike [#119](https://github.com/pila86/1c-dev/issues/119)
- [M5](../milestones/m5-tests.md), spike [119-yaxunit-runuittests.md](../spikes/119-yaxunit-runuittests.md)
- PRD §25 Test API, §26 Test Result
- Внешние: [bia-technologies/yaxunit](https://github.com/bia-technologies/yaxunit),
  [alkoleft/mcp-onec-test-runner](https://github.com/alkoleft/mcp-onec-test-runner) (референс only)
