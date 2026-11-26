# Документация 1c-dev

Навигация по **задаче читателя** (Diátaxis: tutorial / how-to / reference / explanation).

## Хочу быстро начать

1. [README](../README.md) — что это, установка, быстрый старт, Cursor/Kilocode, внешние tools.
2. При необходимости — [руководство](user-guide.md), раздел «Установка» и «Новый проект».

## Хочу сделать сценарий (how-to)

- [Руководство пользователя](user-guide.md) — init, adopt, import, build, test, debug, tools.

## Нужна справка по командам (reference)

- [Справочник CLI](cli-reference.md)
- [MCP для AI-агентов](mcp.md) — подключение и список tools
- Детали флагов: `1c-dev <cmd> --help`

## Хочу понять, как устроено (explanation)

- [Обзор: слои и границы](explanation/overview.md)
- [Зависимости: явное и неявное](explanation/dependencies.md)

## Идеи / proposals (ещё не ADR)

- [Автономный агент: OpenHands + Docker над 1c-dev](proposals/autonomous-agent-sandbox.md) — draft: в этом репо; платформа + EDT + Xvfb/VNC; HASP; OpenHands; draft PR

## Почему так решили (ADR)

Архитектурные решения для углубления и контрибьюторов — не первый вход.

| Тема | ADR |
|------|-----|
| Манифест `.1c-dev/` | [022](adr/022-project-home.md), [004](adr/004-project-manifest.md) |
| Init / adopt | [034](adr/034-smart-init-adopt.md), [027](adr/027-configuration-lifecycle.md) |
| Metadata IR | [011](adr/011-metadata-ir-v1.md), [018](adr/018-metadata-types-coverage.md) |
| XML / EDT | [032](adr/032-edt-source-adapter.md) |
| Build / check | [008](adr/008-ibcmd-build.md), [009](adr/009-ibcmd-check.md), [030](adr/030-designer-check-modules.md) |
| Runtime / publish | [019](adr/019-runtime-client-lifecycle.md), [025](adr/025-publish-backends.md) |
| Тесты | [029](adr/029-test-api.md) |
| Отладка | [031](adr/031-debug-api-http.md) |
| Toolchain cache | [013](adr/013-packaging-toolchain-cache.md) |
| External tools | [033](adr/033-external-tools-manager.md) |
| IDE / MCP | [016](adr/016-ide-configure.md), [010](adr/010-mcp-architecture.md) |
| Docs API | [017](adr/017-docs-bsl-context.md) |

Полный индекс: [adr/README.md](adr/README.md).

## Разработка репозитория

- [CONTRIBUTING](../CONTRIBUTING.md)
- [Roadmap](roadmap.md)
- [Архив](archive/README.md) — PRD v0.1, milestones M1–M7
