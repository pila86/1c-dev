# Прототип инструмента знаний (coding patterns MCP)

**Статус:** Draft (спека реализации; код — следующий шаг на ветке `spike/coding-patterns-knowledge-ab`)  
**Потребитель:** A/B-эксперимент [coding-patterns-knowledge-ab.md](coding-patterns-knowledge-ab.md)  
**Рабочие данные:** `.patterns-ab/` (gitignore): клоны, индекс, кэш эмбеддингов, опционально feedback

Документ описывает, **как должен работать прототип**, который предстоит написать: от allowlist репозиториев до MCP `patterns.*`. Это не продукт и не отдельный git-hosting — временный пакет внутри spike/`1c-dev`, который после вердикта можно вынести в свой репозиторий.

## 1. Назначение

Агент (и человек через CLI) по **текстовому описанию прикладной задачи** получает 1–3 релевантных **coding**-рецепта (паттерна) 1С: краткое when/how, антипаттерны, фрагменты BSL, ссылка на источник.

Не отвечает на:

- «как называется метод платформы» → `docs.*` / bsl-ls;
- «создай справочник / собери базу» → MCP `1c-dev`;
- «как сделать dump CF / web-publish» → out of scope (не indexing).

## 2. Компоненты прототипа

```text
┌─────────────────┐     ┌──────────────┐     ┌─────────────────┐
│ sources.yaml    │────▶│ ingest       │────▶│ normalize       │
│ (allowlist)     │     │ clone/pull   │     │ → Card JSON     │
└─────────────────┘     └──────────────┘     └────────┬────────┘
                                                      │
                                                      ▼
┌─────────────────┐     ┌──────────────┐     ┌─────────────────┐
│ MCP patterns.*  │◀────│ retrieve     │◀────│ index           │
│ search / get    │     │ hybrid rank  │     │ embeddings+meta │
│ (+ feedback)    │     └──────────────┘     └─────────────────┘
└─────────────────┘
```

| Модуль | Ответственность |
|--------|-----------------|
| **config** | `sources.yaml`, пути cache, модель эмбеддингов, фильтр `purpose=coding` |
| **ingest** | Скачать/обновить репозитории по pin (commit/tag), только разрешённые path glob |
| **parse** | Найти skills/rules/markdown, извлечь текст |
| **classify** | Назначить `purpose` + `subdomain` (эвристики + опц. LLM позже) |
| **normalize** | Собрать единую **Card** (схема ниже) |
| **index** | Построить/обновить семантический индекс + метаданные |
| **serve** | MCP stdio (и тонкий CLI `patterns search|get|reindex` для отладки) |
| **feedback** | Локальный ±1 по `card_id` (sqlite), влияет на rank |

Расположение кода (предложение при реализации):

```text
spikes/patterns_knowledge/          # или tools/patterns-knowledge/
  pyproject / часть poetry extras
  sources.yaml
  src/.../ingest.py
  src/.../normalize.py
  src/.../index.py
  src/.../mcp_server.py
  src/.../cli.py
  tests/
```

Данные только под `.patterns-ab/`:

```text
.patterns-ab/
  env.local                 # LLM/embed API keys
  sources.lock.json         # фактические commit SHA после ingest
  mirrors/<owner>/<repo>/   # bare или sparse checkout
  cards/*.json              # нормализованные карточки (или одна cards.jsonl)
  index/                    # векторное хранилище + meta.sqlite
  feedback.sqlite           # плюсы/минусы
```

## 3. Allowlist источников (v0)

Только то, что можно **скачивать и отдавать excerpts** с оглядкой на лицензию. Pin — **commit SHA или tag**, не плавающий `main` без lock.

### 3.1 Включить в ingest (coding)

| id | Репозиторий | License | Paths (glob) | Заметка |
|----|-------------|---------|--------------|---------|
| `unica-coding` | [IngvarConsulting/unica](https://github.com/IngvarConsulting/unica) (~252★) | **LGPL-3.0** (`LICENSE`; GitHub API: NOASSERTION) | см. §3.1.1 | Лучшее покрытие задачи «Ларёк»: `document-posting`, `transactions-locks`, `register-design` |
| `desko77-rules` | [Desko77/claude-code-skills-1c](https://github.com/Desko77/claude-code-skills-1c) | MIT | `rules/**/*.md`, `rules/**/*.mdc` | transactions, coding-standards, anti_patterns, query-*, form_module, bsl-ssl |
| `desko77-coding-skills` | тот же | MIT | `skills/1c-form-patterns/**`, `skills/1c-ssl-patterns/**`, `skills/1c-query-*/**`, `skills/1c-bsp-*/**`, `skills/1c-code-review/**`, `skills/1c-bsl-*/**` | Не весь `skills/` |
| `brake71-ssl` | [brake71/1c-ssl-skills](https://github.com/brake71/1c-ssl-skills) | MIT | `skills/**` | Домен БСП |
| `pauk` | [Mempemp/Pauk_1C](https://github.com/Mempemp/Pauk_1C) | MIT | `pauk-product/**/SKILL.md`, coding skills paths по факту дерева | Мало ★ — низкий trust, ручной QA |

**Не писать** собственные «эталонные» рецепты под задачу эксперимента (confounding A/B). Индекс = только внешние allowlist-источники.

### 3.1.1 Unica — что брать / не брать

Плагин Unica = **skills + MCP `unica`** (метаданные/runtime). Для knowledge-индекса `1c-dev` берём **только coding-скиллы** (рецепты BSL/прикладной модели), не ops и не внутренние `.agents/` / `arch/rules/` продукта Unica.

**Include (coding) — `plugins/unica/skills/<name>/SKILL.md` (+ локальные `references/**` рядом со скиллом) и platform-рецепты `plugins/unica/references/platform/{document-posting,transactions-locks,object-locks,register-design,form-events,object-events,module-placement,metadata-modeling,integration-contracts}.md`:**

| skill | subdomain |
|-------|-----------|
| `document-posting` | `document_posting` |
| `transactions-locks` | `transactions_locks` |
| `object-locks` | `transactions_locks` |
| `register-design` | `accumulation_register` |
| `query-optimize` | `queries` |
| `form-patterns` | `forms_client_server` |
| `form-events` | `forms_client_server` |
| `object-events` | `document_posting` / `code_style` |
| `bsp-patterns` | `bsp_ssl` |
| `localization` | `strings_nstr` |
| `module-placement` | `code_style` |
| `background-jobs` | `code_style` / other_coding |
| `data-exchange` | other_coding |
| `integration-implement` | other_coding |
| `api-design` | other_coding |
| `code-review` | `code_style` |
| `security-auth-crypto` | other_coding |
| `metadata-modeling` | borderline → coding, если про модель данных, не про XML dump |
| `data-separation` | other_coding |

**Exclude (не coding для нашего индекса):**

- `meta-add`, `meta-edit`, `meta-info`, `cf-*`, `cfe-*`, `form-compile`, `form-edit`, `role-edit`, `subsystem-edit`, `interface-edit`, `epf-*`, `erf-*`, `xdto`, `code-patch`, `code-search`, `code-diagnostics` — metadata / tool-routing к MCP `unica`;
- `db-*`, `autonomous-server`, `source-access`, `platform-help`, `log-analysis`, `release-support` — runtime/ops;
- `test-authoring` — testing;
- `unica-dev` и всё под `.agents/skills/`, `arch/rules/**` — process / внутренняя архитектура Unica.

**Лицензия LGPL-3.0:** excerpts в Card допустимы при сохранении `license`, `repo_url`, `path`, `commit` и наличии текста LGPL/GPL notice в поставке прототипа (например `.patterns-ab/NOTICE` или копия `LICENSE` из зеркала). Не релицензировать тексты Unica как MIT. Смешение с MIT-карточками в одном индексе ок, если у каждой Card свой `source.license`. Для коммерческого SaaS-зеркала всего плагина — отдельная юр. оценка; для локального A/B + attribution — приемлемо для прототипа.

### 3.2 Опционально (флаг `experimental`)

| id | Репозиторий | License | Условие |
|----|-------------|---------|---------|
| `comol-rules` | [comol/ai_rules_1c](https://github.com/comol/ai_rules_1c) | нет SPDX; README «берите» | Только `content/rules/` coding-список; в Card `license=informal` |

### 3.3 Явно не скачивать / не индексировать

| Репозиторий / контент | Почему |
|----------------------|--------|
| Nikolay-Shirokov/cc-1c-skills (целиком) | Ops/metadata skills, не coding-корпус |
| Unica целиком / MCP-бинарь / `arch/rules` / meta-*-skills | Не наш runtime; индексируем только coding-скиллы §3.1.1 |
| Desko77 `skills/1c-db-*`, `1c-web-*`, `1c-meta-*`, `1c-cf-*`, form-compile… | purpose≠coding |
| Arman-Kudaibergenov/1c-ai-development-kit | AGPL-3.0 — риск для сетевого MCP |
| SteelMorgan/1c-agent-based-dev-framework | PolyForm Small Business — не универсальный продукт |
| burlakovmb/AIAgentSkillsFor1CEDT | Запрет редистрибуции набора |
| Dach-Coin/claude_rules_1c и любые без LICENSE | Нет права на копию |
| SolovievHub / mcp-1c-standards **тексты ИТС** | IP фирмы 1С |
| Любой web-scrape ИТС | Out of scope |

### 3.4 Формат `sources.yaml`

```yaml
version: 1
default_purpose_filter: coding
mirrors_dir: ".patterns-ab/mirrors"
cards_dir: ".patterns-ab/cards"
index_dir: ".patterns-ab/index"

sources:
  - id: unica-coding
    url: https://github.com/IngvarConsulting/unica.git
    ref: main
    license: LGPL-3.0
    trust: 0.9
    include:
      - "plugins/unica/skills/document-posting/**"
      - "plugins/unica/skills/transactions-locks/**"
      - "plugins/unica/skills/object-locks/**"
      - "plugins/unica/skills/register-design/**"
      - "plugins/unica/skills/query-optimize/**"
      - "plugins/unica/skills/form-patterns/**"
      - "plugins/unica/skills/form-events/**"
      - "plugins/unica/skills/object-events/**"
      - "plugins/unica/skills/bsp-patterns/**"
      - "plugins/unica/skills/localization/**"
      - "plugins/unica/skills/module-placement/**"
      - "plugins/unica/skills/background-jobs/**"
      - "plugins/unica/skills/data-exchange/**"
      - "plugins/unica/skills/integration-implement/**"
      - "plugins/unica/skills/api-design/**"
      - "plugins/unica/skills/code-review/**"
      - "plugins/unica/skills/security-auth-crypto/**"
      - "plugins/unica/skills/metadata-modeling/**"
      - "plugins/unica/skills/data-separation/**"
    subdomain_hints:
      "**/document-posting/**": document_posting
      "**/transactions-locks/**": transactions_locks
      "**/object-locks/**": transactions_locks
      "**/register-design/**": accumulation_register
      "**/query-optimize/**": queries
      "**/form-patterns/**": forms_client_server
      "**/form-events/**": forms_client_server
      "**/bsp-patterns/**": bsp_ssl
      "**/localization/**": strings_nstr
      "**/module-placement/**": code_style
      "**/code-review/**": code_style

  - id: desko77-rules
    url: https://github.com/Desko77/claude-code-skills-1c.git
    ref: main                    # резолвится в SHA → sources.lock.json
    license: MIT
    trust: 0.8
    include:
      - "rules/**/*.md"
      - "rules/**/*.mdc"
    exclude:
      - "rules/sdd-workflow.md"
      - "rules/model-selection.md"
      - "rules/agent-*.md"
      - "rules/git-safety-rules.md"
      - "rules/mcp-tool-priority.md"
      - "rules/skill-design.md"
      - "rules/file-edit-efficiency.md"
      - "rules/text-formatting.md"
      - "rules/edt-*.md"          # metadata/tooling EDT — не coding-рецепт
    subdomain_hints:
      "**/1c-transactions-and-locks.md": transactions_locks
      "**/anti_patterns.md": queries
      "**/1c-coding-standards.md": code_style
      "**/query-*.md": queries
      "**/form_module_rules.md": forms_client_server
      "**/bsl-ssl.md": bsp_ssl

  - id: desko77-coding-skills
    url: https://github.com/Desko77/claude-code-skills-1c.git
    ref: main
    license: MIT
    trust: 0.75
    include:
      - "skills/1c-form-patterns/**"
      - "skills/1c-ssl-patterns/**"
      - "skills/1c-query-optimization/**"
      - "skills/1c-query-validate/**"
      - "skills/1c-bsp-api/**"
      - "skills/1c-bsp-command/**"
      - "skills/1c-bsp-registration/**"
      - "skills/1c-code-review/**"
      - "skills/1c-bsl-validate/**"

  - id: brake71-ssl
    url: https://github.com/brake71/1c-ssl-skills.git
    ref: main
    license: MIT
    trust: 0.7
    include: ["skills/**"]

```

`sources.lock.json` после ingest: `{ "desko77-rules": { "commit": "<sha>", "fetched_at": "…" }, … }`.

## 4. Ingest: скачивание и обновление

### 4.1 Команда

```bash
poetry run patterns-knowledge ingest [--source ID] [--force]
```

(имя CLI уточнится при реализации; смысл — один entrypoint.)

### 4.2 Алгоритм

1. Прочитать `sources.yaml`.
2. Для каждого remote source:
   - `git clone --filter=blob:none` (или обычный clone) в `.patterns-ab/mirrors/<id>/`, если нет;
   - `git fetch` + `git checkout` на `ref`;
   - записать **фактический** `commit` в lock;
   - собрать список файлов по `include`/`exclude` (pathspec).
3. Для каждого файла → parse → classify → одна или несколько Card (большой rule можно резать на секции по `##` заголовкам, max размер тела ~2–4k токенов эквивалента).
4. Записать `.patterns-ab/cards/<card_id>.json` (или `cards.jsonl`).
5. Вызвать **reindex** (§6).

Идемпотентность: повторный ingest с тем же SHA не пересобирает embeddings, если content-hash карточки не изменился.

### 4.3 Сеть и секреты

- GitHub: публичные HTTPS clone; `GITHUB_TOKEN` опционально (rate limit).
- Не коммитить mirrors/index в git `1c-dev`.
- Эмбеддинги: тот же или отдельный OpenAI-compatible endpoint из `env.local` (`EMBEDDING_BASE_URL`, `EMBEDDING_API_KEY`, `EMBEDDING_MODEL`).

## 5. Нормализация: схема Card

Каждая единица знания — JSON:

```json
{
  "id": "desko77-rules--1c-transactions-and-locks",
  "purpose": "coding",
  "subdomain": "transactions_locks",
  "title": "Транзакции и управляемые блокировки",
  "summary": "1–3 предложения: когда применять.",
  "when_to_use": ["проведение с записью в БД", "пакетная обработка"],
  "anti_patterns": ["глотать исключение без отката", "долгая транзакция с запросами UI"],
  "body_markdown": "сжатый текст рецепта…",
  "code": [
    { "lang": "bsl", "caption": "канонический шаблон", "text": "…" }
  ],
  "source": {
    "repo_id": "desko77-rules",
    "repo_url": "https://github.com/Desko77/claude-code-skills-1c",
    "path": "rules/1c-transactions-and-locks.md",
    "commit": "abc123…",
    "license": "MIT",
    "trust": 0.8
  },
  "quality": {
    "stars_repo": 95,
    "forks_repo": 18,
    "feedback_score": 0,
    "feedback_n": 0
  },
  "content_hash": "sha256:…",
  "indexed_at": "ISO-8601"
}
```

Правила:

- В индекс и в MCP попадают **только** `purpose == "coding"`.
- `id` стабильный: `{repo_id}--{slug(path)}` (+ суффикс секции при split).
- `body_markdown` / `code` — excerpt, не обязательно весь файл; в `source` всегда путь и commit для attribution (MIT notice).
- Звёзды/форки — **слабый** tie-breaker в rank, не главный сигнал (trust из allowlist важнее).

### 5.1 Classify purpose / subdomain

Порядок:

1. Path/name heuristics (см. exclude ops; keywords: `transaction`, `query`, `form_module`, `ssl`, `coding-standards`, `anti_pattern`, `posting`, `проведен`…).
2. Hints из `sources.yaml` `subdomain_hints`.
3. Если не уверен — `subdomain=other_coding` и пониженный score; в v0 **не** звать LLM для классификации (отложено).
4. Если эвристика говорит metadata/runtime/process — карточку **не писать** (drop).

Поддомены — как в A/B-спеке: `document_posting`, `accumulation_register`, `transactions_locks`, `strings_nstr`, `queries`, `forms_client_server`, `bsp_ssl`, `code_style`, …

## 6. Семантический индекс

### 6.1 Что индексируется

Разделение **поиска** и **выдачи**:

| Поле | Назначение |
|------|------------|
| `_embed_text` (только индекс) | Шапка: `title + summary + subdomain + when_to_use + anti_patterns`. Без полного body и code. |
| `summary` | Skills: YAML `description` (или `summary`). Rules: 2–4 абзаца после H1 до первого `##` / `---`. |
| `body_markdown` | Урезанный рецепт для `patterns.get` (~4k): без секций `MCP routing` / tool-workflow / UTF-8 readme; с Core model, Design rules, примерами BSL. |
| `code` | Фрагменты из trimmed body (если есть). |

```text
_embed_text = title + summary + subdomain + when_to_use + anti_patterns
```

Unica: в allowlist также `plugins/unica/references/platform/{document-posting,transactions-locks,register-design,…}.md` — там основное «мясо» рецептов, а `SKILL.md` даёт сильную шапку для retrieval.

Метаданные в sqlite (или рядом): `id`, `subdomain`, `purpose`, `trust`, `license`, `repo_id`, `content_hash`, пути к полному JSON.

### 6.2 Стек v0 (практичный)

| Слой | Выбор прототипа | Альтернатива |
|------|-----------------|--------------|
| Embeddings | OpenAI-compatible `/v1/embeddings` (локально: nomic / bge через Ollama или sentence-transformers) | Чисто локальный `fastembed` / `sentence-transformers` без HTTP |
| Vector store | **Chroma** (embedded, файлы в `.patterns-ab/index/`) или **sqlite-vec** | FAISS + pickle |
| Meta | SQLite | JSONL |

Конфиг в env:

```bash
export EMBEDDING_BASE_URL=http://127.0.0.1:11434/v1
export EMBEDDING_API_KEY=ollama
export EMBEDDING_MODEL=nomic-embed-text
# либо:
export PATTERNS_EMBEDDING_BACKEND=fastembed
export PATTERNS_EMBEDDING_MODEL=BAAI/bge-m3
```

### 6.3 Retrieve (hybrid)

`patterns.search(query, task?, limit=3)`:

1. Если передан `task`/`subdomain` — prefilter метаданных.
2. Embedding(query) → top-k векторный поиск (k=10–20).
3. Опционально BM25/FTS по `title+summary` (sqlite FTS5) → merge (RRF или сумма нормализованных score).
4. Re-rank:  
   `final = w1*sim + w2*trust + w3*feedback + w4*log1p(stars)`  
   с малыми w3/w4.
5. Вернуть **≤ limit** кратких hit’ов (без полного `body`/`code` — они в `get`).

`patterns.get(id)` — полный Card JSON из `cards/`.

### 6.4 Команда индексации

```bash
poetry run patterns-knowledge reindex [--full]
```

- `--full` — пересчитать все embeddings;
- по умолчанию — только карточки с новым `content_hash`.

## 7. MCP и CLI

### 7.1 Tools

| Tool | Назначение |
|------|------------|
| `patterns.search` | `query`, опц. `task`, `limit` → hits |
| `patterns.get` | `id` → full card |
| `patterns.feedback` | `id`, `vote: +1\|-1`, опц. `note` → пишется в feedback.sqlite (локально) |
| `patterns.stats` (опц. debug) | число карточек, дата ingest, модель эмбеддингов |

Только coding: сервер **игнорирует** запросы на другие purpose (фильтра нет смысла — в индексе их нет).

### 7.2 Ответ search (краткий)

```json
{
  "hits": [
    {
      "id": "…",
      "title": "…",
      "summary": "…",
      "subdomain": "document_posting",
      "score": 0.81,
      "source": { "repo_url": "…", "path": "…", "license": "MIT" }
    }
  ]
}
```

### 7.3 Запуск

```bash
poetry run patterns-knowledge mcp
# stdio FastMCP, по аналогии с 1c-dev mcp
```

В конфиге OpenCode / Cursor для прогона B:

```json
{
  "mcpServers": {
    "1c-dev": { "command": "poetry", "args": ["run", "1c-dev", "mcp"] },
    "patterns": { "command": "poetry", "args": ["run", "patterns-knowledge", "mcp"] }
  }
}
```

(точные args — от layout пакета).

### 7.4 Feedback

- Хранится только локально в `.patterns-ab/feedback.sqlite`.
- Не синхронизируется в git и не требует аккаунтов.
- В v0 достаточно для проверки идеи «агент/человек минусанул вредный пример».

## 8. Pipeline для A/B «Ларёк»

Перед прогоном B:

```bash
source .patterns-ab/env.local
poetry run patterns-knowledge ingest
poetry run patterns-knowledge reindex
# smoke:
poetry run patterns-knowledge search "проведение документа регистр остатков товаров" --task document_posting
poetry run patterns-knowledge search "транзакции блокировки" --task transactions_locks
```

Ожидание smoke: в top-3 есть карточки про проведение/движения/транзакции — в первую очередь из **Unica** (`document-posting`, `register-design`, `transactions-locks`) и/или Desko77 rules.

## 9. Этапы реализации прототипа (для исполнителя)

| Этап | Deliverable | Критерий готовности |
|------|-------------|---------------------|
| P0 | Каркас пакета + `sources.yaml` (без самописных рецептов) | файлы на месте |
| P1 | ingest clone + parse md → cards JSON (без vectors) | `cards/` заполнен, только coding |
| P2 | embeddings + search CLI | smoke запросы §8 дают релевантный top-3 |
| P3 | MCP `search`/`get`/`feedback` | агент tools/list видит patterns |
| P4 | Подключить к harness B | A/B protocol фаза 1–2 закрыта |
| P5+ | comol optional, лучший classify, web-search | после вердикта A/B |

Минимальный путь к эксперименту: **P0–P4**. Семантика (P2) — часть прототипа, не «потом»; без неё search по одной подстроке слишком хрупкий для честного A/B.

## 10. Non-goals прототипа

- Краулинг всего GitHub / поиск в сети по запросу.
- LLM-переписывание карточек «на лету».
- Автопрогон примеров BSL в ИБ.
- Централизованный рейтинг между машинами.
- Отдача полных чужих репозиториев в контекст агента (только card excerpt + ссылка).

## 11. Критерии приёмки прототипа (до агентского A/B)

- [ ] `ingest` отрабатывает allowlist §3.1 без ошибок сети (или skip с явной причиной).
- [ ] В `cards/` нет primary purpose metadata/runtime/process (выборочный audit + unit на classify).
- [ ] `search "оприходование товаров регистр остатков"` → hit с subdomain posting/register в top-3.
- [ ] `search "НачатьТранзакцию проведение"` → hit transactions.
- [ ] `get` возвращает code или body + license/source path.
- [ ] MCP stdio поднимается; `patterns.feedback` пишет строку в sqlite.
- [ ] Повторный ingest того же SHA не дублирует карточки с тем же `id`.

## 12. Связь документов

| Документ | Роль |
|----------|------|
| **Этот файл** | Как устроен и пишется прототип знаний |
| [coding-patterns-knowledge-ab.md](coding-patterns-knowledge-ab.md) | Зачем A/B и как гонять агента «Ларёк» |
| [coding-patterns-knowledge-ab-protocol.md](coding-patterns-knowledge-ab-protocol.md) | Журнал прогонов |
