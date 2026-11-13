# Coding knowledge A/B — protocol

**Статус:** документация готова; прогоны не начаты.  
**Спека эксперимента:** [coding-patterns-knowledge-ab.md](coding-patterns-knowledge-ab.md)  
**Фикстуры:** `.patterns-ab/` (gitignore)

## Header / env

| Ключ | Значение |
|------|----------|
| Дата старта | _TBD_ |
| Ветка | `spike/coding-patterns-knowledge-ab` |
| Platform 1С | _TBD_ (path + version) |
| 1c-dev | _TBD_ (`poetry run 1c-dev --version` / commit) |
| CLI-агент | _TBD_ (например OpenCode) + version |
| Модель | _TBD_ (`PATTERNS_AB_MODEL`) |
| LLM endpoint | _TBD_ (`OPENAI_BASE_URL`, без секрета) |
| patterns MCP | _TBD_ (команда запуска stdio) |
| Fixture root | `$REPO/.patterns-ab/` |

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
| poetry install / doctor | ☐ | |
| CLI-агент установлен | ☐ | |
| LLM отвечает на chat/completions | ☐ | |
| `.patterns-ab/env.local` создан | ☐ | не коммитить |
| `.patterns-ab/` в gitignore | ☐ | |

## Фаза 1 — Прототип patterns

Спека: [coding-patterns-knowledge-tool.md](coding-patterns-knowledge-tool.md).

| Шаг | Статус | Заметка |
|-----|--------|---------|
| P0 seed + sources.yaml | ☐ | |
| P1 ingest → cards (coding only) | ☐ | |
| P2 embeddings + search CLI | ☐ | |
| P3 MCP search/get/feedback | ☐ | |
| Приёмка §11 tool-спеки | ☐ | |
| smoke «проведение остатков» | ☐ | |
| smoke «транзакции» | ☐ | |

Команды:

```text
ingest:  _TBD_
reindex: _TBD_
mcp:     _TBD_
```

## Фаза 2 — Workspace template

Команды init (зафиксировать после первого успеха):

```bash
_TBD_
```

| Шаг | Статус | Заметка |
|-----|--------|---------|
| Шаблон A: только 1c-dev MCP | ☐ | |
| Шаблон B: 1c-dev + patterns + строка AGENTS | ☐ | |

## Фаза 3 — Run A (control)

```text
run: A
timestamp:
agent:
model:
patterns_mcp: no
workspace: .patterns-ab/runs/A-…/workspace
wall_time_s:
agent_exit:
M1:
M2:
M3:
M4:
M5:
M6:
M7:
patterns_calls: 0
notes:
artifacts:
```

### Acceptance detail A

| ID | Result | Evidence |
|----|--------|----------|
| M1 project | ☐ | |
| M2 catalog Товары | ☐ | |
| M3 register stock | ☐ | |
| M4 document receipt | ☐ | |
| M5 posting movements | ☐ | |
| M6 build | ☐ | |
| M7 check | ☐ | |

### Should A

| ID | Result | Notes |
|----|--------|-------|
| S1 transactions style | ☐ | |
| S3 no query-in-loop | ☐ | |

## Фаза 4 — Run B (treatment)

```text
run: B
timestamp:
agent:
model:
patterns_mcp: yes
workspace: .patterns-ab/runs/B-…/workspace
wall_time_s:
agent_exit:
M1:
M2:
M3:
M4:
M5:
M6:
M7:
patterns_calls: n / ids=
notes:
artifacts:
```

### Acceptance detail B

| ID | Result | Evidence |
|----|--------|----------|
| M1 project | ☐ | |
| M2 catalog Товары | ☐ | |
| M3 register stock | ☐ | |
| M4 document receipt | ☐ | |
| M5 posting movements | ☐ | |
| M6 build | ☐ | |
| M7 check | ☐ | |

### Should B

| ID | Result | Notes |
|----|--------|-------|
| S1 transactions style | ☐ | |
| S2 patterns.* used | ☐ | ids: |
| S3 no query-in-loop | ☐ | |

## Фаза 5 — Вердикт

| Поле | Значение |
|------|----------|
| Вердикт | _TBD_ — knowledge помогает / не влияет / мешает / прогон невалиден |
| A must | PASS / FAIL |
| B must | PASS / FAIL |
| Сравнение проведения | _TBD_ |
| Решение дальше | _TBD_ — отдельный repo / stub only / drop |
| Дата вердикта | _TBD_ |

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
