# Coding knowledge A/B — protocol

**Статус:** прототип + Cognitum A/B прогоны; успешный treatment B на 100 шагах.  
**Спека эксперимента:** [coding-patterns-knowledge-ab.md](coding-patterns-knowledge-ab.md)  
**Фикстуры:** `.patterns-ab/` (gitignore)

## Header / env

| Ключ | Значение |
|------|----------|
| Дата старта | 2026-11-13 |
| Ветка | `spike/coding-patterns-knowledge-ab` |
| Platform 1С | 8.5.1.1529 (`/opt/1cv8/x86_64/8.5.1.1529`) |
| 1c-dev | `1c-dev 0.1.0` |
| CLI-агент | OpenCode `1.19.5` |
| Модель | `cognitum/qwen3.8:27b` (+ DeepSeek free smoke) |
| LLM endpoint | Cognitum OpenAI-compatible (`LLM_BASE_URL`, через HTTP proxy) |
| patterns MCP | `poetry run patterns-knowledge mcp` |
| Fixture root | `$REPO/.patterns-ab/` |
| Fresh runs | DeepSeek free: `A/B-…1410*`; Cognitum: см. строки A/B ниже |
| Transcript | `agent.transcript.md` = текст модели + tool + **output/error** (trim ~4k); `patterns-knowledge transcript` / live `agent-run` |
| Steps limit | `PATTERNS_AB_STEPS` (default 40; успешный B = 100) → `opencode.json` `agent.build.steps` |
| Cognitum A | `A-…150421Z` **killed** (путаница регистратор/EDT/`find /`); ранее `A-…144254Z` steps=50 — неверный API проведения |
| Cognitum B | **`B-20261113T152016Z` steps=100, ~6.5 мин, exit 0**: patterns search+get `document-posting`; `ОбработкаПроведения` + `ДобавитьПриход`; build/check ok. Оговорка: нет `Записывать=Истина` при `WriteSelected`. Ранее `B-…150423Z` steps=50 — лимит, пустой модуль; `B-…144910Z` steps=50 — тоже зелёный build/check |

```bash
# Пример (подставить свои пути; секреты — только из env.local)
cd /path/to/1c-dev
set -a && source .patterns-ab/env.local && set +a
export PATTERNS_AB_ROOT="$PWD/.patterns-ab"
poetry run 1c-dev doctor
```

## Фаза 0 — Prep

| Шаг | Статус | Заметка |
|-----|--------|---------|
| poetry install / doctor | ✅ | platform 8.5.1.1529 |
| CLI-агент установлен | ✅ | opencode 1.19.5 |
| LLM отвечает на chat/completions | ☐ | ждём `env.local` |
| `.patterns-ab/env.local` создан | ☐ | есть `env.local.example` |
| `.patterns-ab/` в gitignore | ✅ | |

## Фаза 1 — Прототип patterns

Спека: [coding-patterns-knowledge-tool.md](coding-patterns-knowledge-tool.md).

| Шаг | Статус | Заметка |
|-----|--------|---------|
| P0 sources.yaml (без рукописного seed) | ✅ | unica + desko77 + brake71 |
| P1 ingest → cards (coding only) | ✅ | 132 cards |
| P2 embeddings + search CLI | ✅ | TF-IDF fallback; шапка в индекс |
| P3 MCP search/get/feedback | ✅ | |
| Приёмка §11 tool-спеки | ✅ | partial |
| smoke «проведение остатков» | ✅ | #1 Document Posting |
| smoke «транзакции» | ✅ | #1 Transactions Locks |

Команды:

```text
ingest:  poetry run patterns-knowledge ingest --force
reindex: poetry run patterns-knowledge reindex
mcp:     poetry run patterns-knowledge mcp
```

## Фаза 2 — Workspace template

Команды init:

```bash
poetry run python -m patterns_knowledge.harness A
poetry run python -m patterns_knowledge.harness B
```

| Шаг | Статус | Заметка |
|-----|--------|---------|
| Шаблон A: только 1c-dev MCP | ✅ | `A-20261113T141022Z` |
| Шаблон B: 1c-dev + patterns + строка AGENTS | ✅ | `B-20261113T141023Z` |

## Фаза 3 — Run A (control)

```text
run: A
timestamp: 2026-11-13T17:11:59+03 → 17:17:43+03 (~344s)
agent: opencode 1.19.5
model: opencode/deepseek-v4.1-flash-free
patterns_mcp: no
workspace: .patterns-ab/runs/A-20261113T141022Z/workspace
wall_time_s: ~344
agent_exit: 0
M1: PASS
M2: PASS Catalog.Товары
M3: PASS AccumulationRegister.ОстаткиТоваров (Товар→CatalogRef.Товары, Количество Number 15.3)
M4: PASS Document.ОприходованиеТоваров + ТЧ Товары
M5: PASS ОбработкаПроведения → Движения.ОстаткиТоваров Приход
M6: PASS (агент + повторный build ok)
M7: спорно — агент получил check ok; независимый повтор → FAIL 1CC004 CheckModules 255
patterns_calls: 0
notes: ~53 tools; много ошибок 1CM004 на форматах типов; UTF-8 BOM в ObjectModule.bsl; без транзакции/блокировок
artifacts: agent.jsonl, agent.stderr.log, build.json
```

### Acceptance detail A

| ID | Result | Evidence |
|----|--------|----------|
| M1 project | ✅ | metadata list / project root ok |
| M2 catalog Товары | ✅ | `Catalog.Товары` |
| M3 register stock | ✅ | `ОстаткиТоваров` dim+resource |
| M4 document receipt | ✅ | `ОприходованиеТоваров` + ТЧ |
| M5 posting movements | ✅ | ObjectModule.bsl Приход |
| M6 build | ✅ | status ok (create/import/apply) |
| M7 check | ⚠️ | agent: ok; recheck: 1CC004 |

### Should A

| ID | Result | Notes |
|----|--------|-------|
| S1 transactions style | ❌ | простой цикл, без НачатьТранзакцию / блокировок |
| S3 no query-in-loop | ✅ | запроса в цикле нет |

## Фаза 4 — Run B (treatment)

```text
run: B
timestamp: 2026-11-13T17:19:28+03 → 17:22:09+03 (~161s)
agent: opencode 1.19.5
model: opencode/deepseek-v4.1-flash-free
patterns_mcp: yes
workspace: .patterns-ab/runs/B-20261113T141023Z/workspace
wall_time_s: ~161
agent_exit: 0
M1: PASS
M2: PASS Catalog.Товары
M3: PASS AccumulationRegister.ОстаткиТоваров
M4: PASS Document.ОприходованиеТоваров + ТЧ
M5: слабо — движения есть, но НЕТ ВидДвиженияНакопления.Приход и Период (хуже A)
M6: PASS (агент + повторный build ok)
M7: спорно — агент check ok; независимый повтор FAIL 1CC004 (как A; BOM в .bsl)
patterns_calls: 4 — search×2 + get×2
  ids: unica-coding--document-posting--skill, unica-coding--metadata-modeling--skill
notes: быстрее A; patterns звал рано; проведение проще/хуже A; второй search ушёл в metadata DSL (шум)
artifacts: agent.jsonl, build.json, check.json
```

### Acceptance detail B

| ID | Result | Evidence |
|----|--------|----------|
| M1 project | ✅ | |
| M2 catalog Товары | ✅ | |
| M3 register stock | ✅ | |
| M4 document receipt | ✅ | |
| M5 posting movements | ⚠️ | цикл Есть; нет `ВидДвижения`/`Период` |
| M6 build | ✅ | |
| M7 check | ⚠️ | agent ok; recheck 1CC004 |

### Should B

| ID | Result | Notes |
|----|--------|-------|
| S1 transactions style | ❌ | без транзакции/блокировок |
| S2 patterns.* used | ✅ | document-posting + metadata-modeling |
| S3 no query-in-loop | ✅ | |

## Фаза 5 — Вердикт

| Поле | Значение |
|------|----------|
| Вердикт | **не влияет / слабо мешает качеству BSL** на этой модели: S2 выполнен, но проведение B хуже A; ускорение wall-time (~161s vs ~344s) есть |
| A must | условный PASS (M7 flaky) |
| B must | условный PASS (M5 слабее, M7 flaky) |
| Сравнение проведения | A задаёт `ВидДвижения.Приход` + `Период`; B — нет |
| Решение дальше | повторить на более сильной модели (ceiling) и/или усилить card body (явный BSL snippet Приход); M7/BOM — отдельный баг harness |
| Дата вердикта | 2026-11-13 (предварительный, free DeepSeek) |

Краткое summary также внести в §16 файла [coding-patterns-knowledge-ab.md](coding-patterns-knowledge-ab.md).

## Опционально — Run C (ceiling)

```text
run: C
timestamp:
agent:
model:          # облачная, если использовалась
patterns_mcp: yes|no
notes:          # зачем: отделить H_confound
```
