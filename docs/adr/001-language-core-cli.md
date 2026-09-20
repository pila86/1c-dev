# ADR-001: Язык реализации core/CLI

**Статус:** Accepted  
**Дата:** 2026-09-01  
**Принято:** 2026-09-10

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
| Скорость vibe-coding / итераций | + | − | ++ |
| Типизация / refactor safety | + | ++ | + (type hints + mypy) |
| Java-инструменты (MDClasses) | subprocess | subprocess | subprocess |
| Холодный старт CLI | ++ | ++ | + |

### Python — за

- **Скорость разработки:** Python — единственный из рассматриваемых вариантов, которым автор проекта уже владеет. MVP и последующее вайбкодинг-развитие будут существенно быстрее, чем на Go или Rust с нулевым порогом входа.
- **Характер задачи:** core/CLI в основном занимается orchestration: subprocess, filesystem, XML/JSON, HTTP/MCP, adapters. Это хорошо соответствует сильным сторонам Python; экстремальная производительность здесь не является требованием.
- **Экосистема:** для Python есть зрелые библиотеки для CLI (`typer`, `click`), MCP (`mcp`, FastMCP), JSON/XML (`pydantic`, `lxml`), subprocess, тестирования (`pytest`) и типизации (`mypy`).
- **AI-friendly development:** Python проще читать и ревьюить при разработке через AI — это непосредственно соответствует цели проекта (agent-independent toolchain, разработка с участием AI-агентов).
- **Низкий порог входа для контрибьюторов:** разработчикам, знакомым с Python, проще подключаться к проекту, чем осваивать новый для них Go/Rust stack.
- Быстрый прототип M1
- Subprocess-native модель (ibcmd, 1cv8 — основной паттерн runtime)
- Poetry для воспроизводимого окружения

### Python — против / ограничения

- Нет single-binary из коробки — **не blocker для M1:** distribution/packaging (`pipx`, `uv tool`, PyInstaller) отложено.
- Зависимость от версии Python на машине пользователя (mitigation: Poetry, pin Python 3.11+)

### Go / Rust — за

- Один статический бинарник `1c-dev` без runtime-зависимостей
- Предсказуемая cross-platform дистрибуция «из коробки»
- Rust: максимальная типобезопасность; Go: простота и быстрая компиляция

### Возможность миграции

При необходимости performance- или packaging-критичные части в будущем можно вынести или переписать на Go/Rust, если реальные требования это подтвердят. Архитектура adapter-based это допускает: границы между core и adapters можно сохранить при смене языка ядра.

## Решение

**Принято: Python 3.11+ с менеджером зависимостей Poetry.**

CLI — Typer; entrypoint — `1c-dev`.

Обоснование: скорость итераций M1, зрелый MCP SDK, соответствие orchestration-характеру runtime, владение стеком автором. Отдельный PoC Go/Rust для выбора языка не требуется — критерии и trade-off уже достаточны для M1.

## Альтернативы

| Вариант | Вердикт |
|---------|---------|
| Python 3.11+ + Poetry | Принято |
| Go | Отложено (single-binary / packaging — при необходимости после M1) |
| Rust | Отвергнуто для M1 (высокий порог входа без выигрыша для orchestration) |
| Packaging (`pipx` / `uv tool` / PyInstaller) | Отложено (не блокер M1; must для [M3 Product adopt](../milestones/m3-product-adopt.md)) |

## Последствия

- Scaffold monorepo и CI — под Python/Poetry (см. ADR-002, Issue #1).
- MCP (#6) — через официальный Python SDK (`mcp` / FastMCP).
- Тесты — `pytest` в окружении Poetry.
- Distribution как user install / PATH — [M3](../milestones/m3-product-adopt.md); single-binary — отдельное решение при необходимости.

## Связанные решения

- Issue #1 (ADR и каркас monorepo)
- ADR-002: layout monorepo
- ADR-003: diagnostics model + exit codes
- Будущий ADR-007: MCP architecture
