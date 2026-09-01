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

- **Скорость разработки:** Python — единственный из рассматриваемых вариантов, которым автор проекта уже владеет. MVP и последующее вайбкодинг-развитие будут существенно быстрее, чем на Go или Rust с нулевым порогом входа.
- **Характер задачи:** core/CLI в основном занимается orchestration: subprocess, filesystem, XML/JSON, HTTP/MCP, adapters. Это хорошо соответствует сильным сторонам Python; экстремальная производительность здесь не является требованием.
- **Экосистема:** для Python есть зрелые библиотеки для CLI (`typer`, `click`), MCP (`mcp`, FastMCP), JSON/XML (`pydantic`, `lxml`), subprocess, тестирования (`pytest`) и типизации (`mypy`).
- **AI-friendly development:** Python проще читать и ревьюить при разработке через AI — это непосредственно соответствует цели проекта (agent-independent toolchain, разработка с участием AI-агентов).
- **Низкий порог входа для контрибьюторов:** разработчикам, знакомым с Python, проще подключаться к проекту, чем осваивать новый для них Go/Rust stack.
- Быстрый прототип M1
- Subprocess-native модель (ibcmd, 1cv8 — основной паттерн runtime)
- Poetry/uv для воспроизводимого окружения

### Python — против / ограничения

- Нет single-binary из коробки — **но это не blocker:** отсутствие нативного single-binary следует рассматривать как отдельный вопрос distribution/packaging (`pipx`, `uv tool`, PyInstaller), а не как фундаментальный недостаток языка для M1.
- Зависимость от версии Python на машине пользователя (миtigation: Poetry/uv, pin Python 3.11+)

### Go / Rust — за

- Один статический бинарник `1c-dev` без runtime-зависимостей
- Предсказуемая cross-platform дистрибуция «из коробки»
- Rust: максимальная типобезопасность; Go: простота и быстрая компиляция

### Возможность миграции

При необходимости performance- или packaging-критичные части в будущем можно вынести или переписать на Go/Rust, если реальные требования это подтвердят. Архитектура adapter-based это допускает: границы между core и adapters можно сохранить при смене языка ядра.

## Решение

**TBD** — окончательный выбор не зафиксирован.

Процесс принятия (Issue #1):

1. **PoC:** сравнить Python и Go на реальном сценарии M1 (минимальный CLI + subprocess + JSON output). Rust — опционально, если PoC не выявит явного лидера.
2. Зафиксировать решение в этом ADR с таблицей «принято / отвергнуто / отложено».
3. Если выбран Python — зафиксировать менеджер зависимостей (Poetry vs uv) в этом ADR или ADR-001b.
4. Если выбран Python — отдельно спланировать packaging (не блокер для M1).

## Альтернативы

| Вариант | Вердикт |
|---------|---------|
| Go | TBD |
| Rust | TBD |
| Python | TBD |

## Последствия

После принятия — scaffold monorepo под выбранный язык (см. Issue #1).

## Conclusion

На текущем этапе **Python выглядит сильным кандидатом** благодаря скорости разработки, соответствию характеру задачи (orchestration, не compute-heavy) и AI-friendly nature кодовой базы. Окончательный выбор предлагается сделать **после небольшого PoC**, сравнив Python и Go на реальном сценарии M1.

## Связанные решения

- Issue #1 (ADR и каркас monorepo)
- Будущий ADR-007: MCP architecture
