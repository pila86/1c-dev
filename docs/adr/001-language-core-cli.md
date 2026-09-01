# ADR-001: Язык реализации core/CLI

**Статус:** Proposed  
**Дата:** 2026-09-01

## Контекст

1C Dev Runtime — orchestration layer: subprocess calls (ibcmd, 1cv8), JSON API, MCP server, adapter architecture. Нужен язык для core и CLI (`1c-dev`).

Критерии из PRD §61:

- subprocess / process management
- cross-platform (Windows, Linux)
- простая distribution
- удобный JSON
- plugin/adapter architecture
- минимум runtime dependencies

## Кандидаты

| Критерий | Go | Rust | Python |
|----------|-----|------|--------|
| Один бинарник / простая установка | ++ | ++ | − (venv/poetry/uv) |
| Subprocess / orchestration CLI | ++ | ++ | ++ |
| Cross-platform | ++ | ++ | + |
| MCP SDK и экосистема | + | + | ++ |
| Скорость vibe-coding / итераций | + | + | ++ |
| Типизация / refactor safety | + | ++ | + (type hints + mypy) |
| Java-инструменты (MDClasses) | subprocess | subprocess | subprocess |
| Холодный старт CLI | ++ | ++ | + |

### Python — за

- Быстрый прототип M1
- Богатая экосистема MCP (`mcp`, FastMCP)
- Subprocess-native модель
- Poetry/uv для воспроизводимого окружения

### Python — против

- Нет single-binary из коробки
- Зависимость от версии Python на машине пользователя

### Go / Rust — за

- Один статический бинарник `1c-dev`
- Предсказуемая cross-platform дистрибуция

## Решение

**TBD** — будет зафиксировано в Issue #1 после spike (2–4 часа):

1. Минимальный CLI + subprocess + JSON output на финалистах
2. Таблица «принято / отвергнуто / отложено»
3. Если Python — выбор менеджера зависимостей (Poetry vs uv)

## Альтернативы

| Вариант | Вердикт |
|---------|---------|
| Go | TBD |
| Rust | TBD |
| Python | TBD |

## Последствия

После принятия — scaffold monorepo под выбранный язык (см. Issue #1).

## Связанные решения

- Issue #1 (ADR и каркас monorepo)
- Будущий ADR-007: MCP architecture
