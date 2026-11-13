# Spike: A/B — coding knowledge MCP + агент «Ларёк»

**Статус:** Draft (документация эксперимента; реализация прототипа и прогоны — позже)  
**Ветка:** `spike/coding-patterns-knowledge-ab`  
**Прототип инструмента знаний:** [coding-patterns-knowledge-tool.md](coding-patterns-knowledge-tool.md) (источники, ingest, семантика, MCP)  
**Протокол прогонов:** [coding-patterns-knowledge-ab-protocol.md](coding-patterns-knowledge-ab-protocol.md)  
**Артефакты прогонов (gitignore):** `.patterns-ab/` в корне репозитория

## 1. Цель

Проверить гипотезу:

> Узкий MCP с **прикладными coding-паттернами** 1С (не runtime/ops) повышает качество BSL проведения и движений по регистру остатков у CLI-агента при той же модели и том же `1c-dev`, по сравнению с прогоном **без** этого MCP.

Эксперимент **не** выбирает write-backend и **не** заменяет `docs.*` / bsl-ls. Он отвечает только на вопрос: нужен ли отдельный knowledge-слой для coding в контуре `1c-dev`.

## 2. Гипотеза и антигипотеза

| | Формулировка |
|--|----------------|
| **H1** | В treatment (с `patterns`) агент чаще получает зелёный `build`/`check` и корректные движения регистра; меньше типичных ошибок проведения (нет транзакции, неверные измерения, запись остатков «в лоб» без набора записей). |
| **H0** | Разницы нет: хватает `metadata.*` + `docs.*` + правил из `ide configure`, либо модель игнорирует `patterns.*`. |
| **H_confound** | Локальная LLM слабо вызывает MCP / ломает XML — тогда A≈B по провалу, вывод «knowledge бесполезен» **невалиден**; нужен повтор на более сильной модели (опциональный ceiling-run). |

## 3. Scope / Non-goals

### In scope (v0)

- Прототип инструмента знаний по [coding-patterns-knowledge-tool.md](coding-patterns-knowledge-tool.md): allowlist → clone → normalize Card → **семантический индекс** → MCP `patterns.search` / `get` / `feedback`.
- Только `purpose=coding` (см. §6); приоритетный источник — **IngvarConsulting/unica** (LGPL-3.0, coding-скиллы вроде `document-posting` / `transactions-locks` / `register-design`) + MIT (Desko77, brake71). Без самописных рецептов под задачу.
- Сквозной A/B на задаче «Ларёк» (§7) через headless CLI-агент + `1c-dev` MCP.
- Локальная LLM и локальные/compatible embeddings; креды только через env / `.patterns-ab/env.local`.

### Out of scope (v0)

- Краулинг всего GitHub, web-search, LLM-переписывание карточек, автотесты примеров в ИБ.
- Индексация runtime/ops skills (`db-load`, `web-publish`, meta-compile и т.п.).
- Слияние knowledge в monorepo-продукт `1c-dev` (после вердикта — отдельный ADR/репозиторий).
- Замена `docs.*` (синтакс-помощник) или IDE rules pack.
- Обязательный прогон на облачных моделях (только опциональный ceiling).

## 4. Роли слоёв знаний (чтобы не смешивать)

| Слой | Вопрос агента | Инструмент |
|------|----------------|------------|
| Факты платформы (API, операторы) | «Как называется метод / оператор?» | `docs.*`, bsl-ls |
| Жёсткие guardrails проекта | «Не invent API; порядок build/check» | `AGENTS.md`, IDE rules от `1c-dev` |
| **Прикладной рецепт BSL** | «Как оформить проведение с движениями остатков?» | **`patterns.*` (этот spike)** |
| Операции над проектом | «Создай объект / собери / проверь» | MCP `1c-dev` (`metadata.*`, `build`, `check`, …) |

В treatment в managed-блоке AGENTS (или отдельной строке spike-инструкции) одна явная маршрутизация:

> Прикладной паттерн BSL (проведение, регистры, транзакции, строки) → `patterns.search` / `patterns.get`, не выдумывать.  
> Сборка, ИБ, метаданные объектов → MCP `1c-dev`.  
> Имя платформенного API → `docs.*` / bsl-ls.

В control этой строки про `patterns` **нет** (и MCP `patterns` не подключён).

## 5. Дизайн A/B

Одинаковые: промпт (§8), модель, таймаут/`max_turns`, версия `1c-dev`, платформа 1С, наличие `docs.*`/bsl-ls (как в обычном `ide configure`), чистый workspace на каждый прогон.

| Прогон | MCP | Отличие |
|--------|-----|---------|
| **A — control** | `1c-dev` (+ docs/bsl-ls, если включены в harness) | Нет `patterns` |
| **B — treatment** | A + `patterns` (прототип из tool-спеки) | Есть coding knowledge |

Порядок: сначала A, потом B на **новом** каталоге (не продолжение сессии A).  
Опционально **C — ceiling**: тот же B (или A+B) на облачной модели — только чтобы отделить «слабая LLM» от «плохой knowledge».

На каждый прогон — отдельный git init baseline в фикстуре, чтобы смотреть diff и не тащить историю A в B.

## 6. Таксономия и фильтр «только coding»

Primary purpose артефакта знания:

| purpose | Примеры | В индекс v0 для 1c-dev? |
|---------|---------|-------------------------|
| **coding** | проведение, движения, транзакции, запросы, формы (логика модулей), БСП-паттерны, `НСтр` | **Да** |
| metadata | Form.xml compile, MDO, cf-add-object | Нет |
| runtime | db-load, build scripts, web-publish | Нет (`1c-dev` уже умеет) |
| testing | YaXUnit/Vanessa skills | Нет |
| debug | systematic-debugging skills | Нет |
| process | SDD, memory, model-selection | Нет |
| tooling | PowerShell, mermaid, docx | Нет |

Поддомены `coding` (поле `subdomain` / аргумент `task` у `patterns.search`):

| subdomain | Типичный запрос |
|-----------|-----------------|
| `document_posting` | ОбработкаПроведения, набор записей |
| `accumulation_register` | регистр остатков, измерения/ресурсы, движения |
| `transactions_locks` | НачатьТранзакцию, блокировки, откат |
| `strings_nstr` | НСтр, СтрШаблон |
| `queries` | ВТ, антипаттерн «запрос в цикле» |
| `forms_client_server` | директивы, лишние серверные вызовы |
| `bsp_ssl` | ОбщегоНазначения и др. |
| `code_style` | области, структура модуля |

Stub v0 обязан покрыть минимум: `document_posting`, `accumulation_register`, `transactions_locks` (и желательно `strings_nstr`).

## 7. Задача агента: конфигурация «Ларёк»

### 7.1 Продуктовое ТЗ (фиксированное)

Создать конфигурацию **Ларёк** (`Larek`) с:

1. **Справочник** `Товары` (`Products` / синоним «Товары») — минимум: наименование (как в типовых; доп. реквизиты не требовать в v0).
2. **Регистр накопления** остатков товаров (вид **Остатки**), например `ТоварыНаСкладах` / `ProductStock`:
   - измерение: номенклатура → справочник Товары;
   - ресурс: количество (число).
3. **Документ** `ОприходованиеТоваров` (`GoodsReceipt` / синоним «Оприходование товаров»):
   - табличная часть с товаром и количеством;
   - **проведение** создаёт движения по регистру остатков (приход).

Имена объектов в промпте — русские синонимы + допустимы латинские имена метаданных; в acceptance (§9) сверять по факту `metadata.list` / IR, зафиксировав найденные имена в protocol.

### 7.2 Что агент должен использовать

- Предпочитать MCP `1c-dev` для init / metadata / build / check (не Конфигуратор вручную, не shell вокруг платформы без нужды).
- BSL модулей — писать в source; после правок — diagnostics при наличии bsl-ls, затем `build` и `check`.

### 7.3 Что не требовать в v0

- Склады, серии, характеристики, цены, несколько организаций.
- Расход / перемещение / инвентаризация.
- Полноценный UI сверх минимальной формы документа.
- YaXUnit (опциональный бонус в scoring, не must).

## 8. Промпт агента (verbatim)

Копировать **без изменений** в оба прогона. Не добавлять в control намёков про patterns.

```text
Ты разрабатываешь конфигурацию 1С:Предприятие в этом workspace через доступные MCP-инструменты.

Задача: конфигурация «Ларёк».
1) Справочник «Товары».
2) Регистр накопления остатков товаров (вид Остатки): измерение — товар (ссылка на Товары), ресурс — количество.
3) Документ «Оприходование товаров» с табличной частью (товар, количество) и проведением, которое делает приход по регистру остатков.

Требования:
- Используй MCP 1c-dev для проекта и метаданных (project/configuration/metadata/build/check), не Конфигуратор и не выдуманные CLI платформы.
- Не выдумывай API платформы: уточняй через docs.* / language server, если доступны.
- После создания объектов реализуй модуль проведения документа.
- Добийся успешного build и check.
- Кратко в конце перечисли созданные объекты метаданных и где лежит код проведения.

Не реализуй склады, цены, расход и тесты, если это не нужно для проведения.
```

Для treatment **дополнительно** (только B): в AGENTS/spike-инструкции одна строка маршрутизации §4. Сам пользовательский промпт выше — тот же.

## 9. Acceptance (машинный чеклист)

Прогон считается **PASS**, если все must выполнены. Фиксировать в protocol.

| ID | Must | Как проверить |
|----|------|----------------|
| M1 | Проект 1c-dev валиден | `1c-dev project get` / MCP `project.get` без error |
| M2 | Есть справочник Товары | `metadata.list` / `get` — Catalog |
| M3 | Есть регистр накопления остатков с измерением товар и ресурсом количество | `metadata.get` по регистру |
| M4 | Есть документ оприходования с ТЧ товар+количество | `metadata.get` |
| M5 | В модуле документа есть проведение с движениями по регистру | grep/read ObjectModule (или аналог); движения не пустые по смыслу |
| M6 | `build` успешен | exit 0 / payload ok |
| M7 | `check` успешен | exit 0 / payload ok |

Should (не ломают PASS, влияют на score):

| ID | Should | Заметка |
|----|--------|---------|
| S1 | Транзакция / контролируемый шаблон ошибок в проведении | сравнение A vs B |
| S2 | Вызов `patterns.search`/`get` в B | по логу агента |
| S3 | Нет «запроса в цикле» в проведении | эвристика по коду |
| S4 | Имена/синонимы осмысленные | субъективно + list |

Fail-fast (прогон **FAIL**):

- нет движений в проведении при зелёном build (M5);
- check красный (M7);
- агент создал только метаданные без BSL проведения.

## 10. Scoring A vs B

| Критерий | Вес | Как мерить |
|----------|-----|------------|
| Acceptance must M1–M7 | must | PASS/FAIL |
| Качество проведения (S1, S3) | high | ручной разбор модуля + чеклист в protocol |
| Использование knowledge в B | high | число и релевантность вызовов `patterns.*` |
| Wall time / число шагов агента | med | лог |
| Diff noise / лишние объекты | low | git diff vs baseline |
| Попытки shell/Конфигуратор в обход MCP | med | лог; штраф |

**Вердикт spike (после A и B):**

| Вердикт | Условие |
|---------|---------|
| **knowledge помогает** | B PASS, A FAIL; или оба PASS, но B заметно лучше по S1/S3 и реально звал `patterns` |
| **не влияет** | A≈B по must и качеству; или B не вызывал `patterns` |
| **мешает / шум** | B хуже A при равных условиях |
| **прогон невалиден** | сработал H_confound (модель не ходит в MCP / обрыв по таймауту на обоих) |

## 11. Окружение harness

### 11.1 Каталоги

```text
$REPO/                          # клон 1c-dev, ветка spike/…
$REPO/.patterns-ab/             # gitignore; всё ниже
  env.local                     # секреты LLM; НЕ коммитить
  stub-cards/                   # карточки knowledge (или рядом с прототипом)
  runs/
    A-<timestamp>/
      workspace/                # чистый проект Ларёк
      agent.log
      tools.jsonl               # если агент умеет
      result.md                 # краткий итог
    B-<timestamp>/
      …
  protocol-notes.md             # черновик; итог переносить в docs/spikes/…-protocol.md
```

Добавить в `.gitignore` репозитория: `.patterns-ab/`.

### 11.2 Платформа и 1c-dev

- Установленная платформа 1С (версия — зафиксировать в protocol header).
- `poetry install` в `$REPO`; CLI: `poetry run 1c-dev …`.
- `1c-dev tools sync` (xml-gen / docs-facade по необходимости).
- MCP `1c-dev`: `poetry run 1c-dev mcp` (stdio), как в README продукта.

### 11.3 CLI-агент (рекомендация)

**OpenCode** (`opencode run "…"`): headless, MCP, `AGENTS.md`, OpenAI-compatible / локальные модели.

Альтернативы (если OpenCode недоступен): Claude Code `claude -p`, Codex `codex exec`, Cursor `agent -p` — зафиксировать выбранный бинарь и версию в protocol. Для локальной LLM предпочтителен OpenCode.

Минимальные требования к агенту:

- запуск из CLI без UI;
- подключение ≥2 MCP (`1c-dev`, и в B ещё `patterns`);
- чтение `AGENTS.md` в workspace;
- лог сессии в файл.

### 11.4 Локальная LLM

- Endpoint OpenAI-compatible (Ollama / vLLM / LM Studio / …).
- Модель — одна и та же для A и B; имя и context size — в protocol.
- Креды:

```bash
# .patterns-ab/env.local (пример; не коммитить)
export OPENAI_BASE_URL=http://127.0.0.1:11434/v1
export OPENAI_API_KEY=ollama   # или реальный ключ локального прокси
export PATTERNS_AB_MODEL=…     # id модели у провайдера
```

Перед прогоном: `set -a && source .patterns-ab/env.local && set +a`.

### 11.5 Прототип MCP `patterns`

Полная спека (allowlist, скачивание, Card, embeddings, rank, MCP, этапы P0–P4):  
**[coding-patterns-knowledge-tool.md](coding-patterns-knowledge-tool.md)**.

Краткий контракт tools для harness:

| Tool | Аргументы | Результат |
|------|-----------|-----------|
| `patterns.search` | `query`, опц. `task`, `limit` (default 3) | краткие hits + score + source |
| `patterns.get` | `id` | полная Card (body, code, license, path) |
| `patterns.feedback` | `id`, `vote` ±1 | локальный sqlite |

Перед прогоном B обязателен pipeline: `ingest` → `reindex` → smoke search по проведению/транзакциям (см. tool-спеку). Корпус — только allowlist GitHub, без рукописных подсказок под «Ларёк».

## 12. Runbook (пошагово)

Выполнять атомами; после каждого — запись в [protocol](coding-patterns-knowledge-ab-protocol.md).

### Фаза 0 — Prep

1. Checkout `spike/coding-patterns-knowledge-ab`.
2. `poetry install`, `poetry run 1c-dev doctor` (зафиксировать platform/tools).
3. Установить/проверить CLI-агент; проверить `opencode --version` (или аналог).
4. Поднять локальную LLM; проверить chat completion curl’ом на `$OPENAI_BASE_URL`.
5. Создать `.patterns-ab/env.local` (не коммитить).
6. Убедиться, что `.patterns-ab/` в `.gitignore`.

### Фаза 1 — Прототип patterns (по tool-спеке)

1. Реализовать P0–P4 из [coding-patterns-knowledge-tool.md](coding-patterns-knowledge-tool.md) §9: ingest allowlist + semantic index + MCP.
2. Закрыть чеклист приёмки прототипа (tool-спека §11): smoke search проведение/транзакции.
3. Зафиксировать команды `ingest` / `reindex` / `mcp` в protocol.

### Фаза 2 — Harness workspace template

1. Скрипт или ручные шаги: создать пустой каталог run → `1c-dev init` / `configuration.add` по принятому в продукте API (актуальные имена CLI — из README/`1c-dev --help` на момент прогона; не копировать устаревшие флаги вслепую).
2. `ide configure` для выбранного агента (MCP `1c-dev`; rules; AGENTS).
3. Для шаблона B — добавить MCP `patterns` в конфиг агента + строку маршрутизации §4.
4. Зафиксировать точные команды init в protocol (после первой успешной сборки шаблона).

### Фаза 3 — Прогон A (control)

1. Скопировать/создать чистый workspace под `.patterns-ab/runs/A-<ts>/workspace`.
2. Подключить только MCP без `patterns`.
3. Запустить агента с промптом §8; сохранить полный лог.
4. Прогнать acceptance §9 (`project get`, `metadata list/get`, `build`, `check`, ревью модуля).
5. Заполнить строку Result log в protocol.

### Фаза 4 — Прогон B (treatment)

1. Новый каталог `B-<ts>` (не клон A после правок агента).
2. MCP + `patterns`; тот же промпт §8.
3. Лог + acceptance + отдельно: были ли вызовы `patterns.*` и какие `id`.
4. Сравнить модуль проведения с A.

### Фаза 5 — Вердикт

1. Выставить вердикт §10 в protocol и краткое Summary в конце этого файла (секция Result).
2. Решение: (a) выделенный репозиторий knowledge, (b) оставить stub в spike, (c) не делать knowledge-слой.

## 13. Result log (шаблон одной строки прогона)

```text
run: A|B|C
timestamp: …
agent: opencode|…  version: …
model: …
patterns_mcp: yes|no
workspace: .patterns-ab/runs/…
wall_time_s: …
agent_exit: …
M1..M7: pass|fail (кратко)
patterns_calls: n / ids=…
notes: …
artifacts: agent.log, …
```

Копировать заполненные блоки в [protocol](coding-patterns-knowledge-ab-protocol.md).

## 14. Риски

| Риск | Митигация |
|------|-----------|
| Агент игнорирует MCP | ceiling-run; проверить tools/list в логе |
| Stub слишком узкий / слишком общий | карточки заточить под Ларёк + транзакции |
| Control уже «слишком умный» из-за rules 1c-dev | не добавлять coding-скиллы в control; rules pack продукта оставить как есть (это baseline продукта) |
| Локальная модель не тянет XML метаданных | оценивать отдельно M2–M4 vs M5; knowledge судят по M5/S1 |
| Утечка секретов | только `.patterns-ab/env.local`, gitignore |

## 15. Связь с продуктом

- После положительного вердикта: ADR «coding knowledge MCP» + решение вынести сервис из monorepo или оставить optional tool в toolchain (как docs-facade).
- Интеграция в `1c-dev`: только документация/`ide configure` hook на внешний MCP — **не** раздувать репозиторий коллекцией скиллов.
- Стиль фиксации — как [write-backend-bakeoff](write-backend-bakeoff.md): spike → protocol → вердикт → ADR.

## 16. Result (заполняется после прогонов)

**Вердикт:** _TBD_  
**Дата:** _TBD_  
**Кратко:** _TBD_

## 17. Чеклист готовности к прогону A

- [ ] Ветка `spike/coding-patterns-knowledge-ab`
- [ ] `.patterns-ab/` gitignore + `env.local` с рабочей LLM
- [ ] Stub MCP `patterns` smoke OK
- [ ] CLI-агент headless запускается и видит MCP `1c-dev`
- [ ] Промпт §8 скопирован без правок
- [ ] Protocol header (platform, agent, model) заполнен
- [ ] Команды init workspace записаны в protocol
