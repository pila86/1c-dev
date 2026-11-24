# Документация 1c-dev

Актуальное описание продукта для пользователей и контрибьюторов.

## С чего начать

1. [README](../README.md) — что это, установка, быстрый старт.
2. [Руководство пользователя](user-guide.md) — типовые сценарии от init до build/test/debug.
3. [Справочник CLI](cli-reference.md) — все команды по доменам.
4. [MCP для AI-агентов](mcp.md) — tools и подключение к IDE.

## Продуктовые темы

| Тема | Документ / ADR |
|------|----------------|
| Манифест `.1c-dev/project.yaml` | [ADR-022](adr/022-project-home.md), [ADR-004](adr/004-project-manifest.md) |
| Init / adopt существующего XML/EDT | [ADR-034](adr/034-smart-init-adopt.md), [ADR-027](adr/027-configuration-lifecycle.md) |
| Metadata IR (list/get/create/update/delete) | [ADR-011](adr/011-metadata-ir-v1.md), [ADR-018](adr/018-metadata-types-coverage.md) |
| XML vs EDT source | [ADR-032](adr/032-edt-source-adapter.md) |
| Build / check | [ADR-008](adr/008-ibcmd-build.md), [ADR-009](adr/009-ibcmd-check.md), [ADR-030](adr/030-designer-check-modules.md) |
| Runtime client / publish | [ADR-019](adr/019-runtime-client-lifecycle.md), [ADR-025](adr/025-publish-backends.md) |
| Тесты (YAxUnit) | [ADR-029](adr/029-test-api.md) |
| Отладка (HTTP `dbgs`) | [ADR-031](adr/031-debug-api-http.md) |
| Toolchain cache + packaging | [ADR-013](adr/013-packaging-toolchain-cache.md) |
| External tools (catalog / services) | [ADR-033](adr/033-external-tools-manager.md) |
| IDE configure + MCP | [ADR-016](adr/016-ide-configure.md), [ADR-010](adr/010-mcp-architecture.md) |
| Docs (синтакс-помощник) | [ADR-017](adr/017-docs-bsl-context.md) |

## Для разработчиков репозитория

- [CONTRIBUTING](../CONTRIBUTING.md) — workflow, toolchain, тесты.
- [Roadmap](roadmap.md) — статус этапов и follow-ups.
- [ADR](adr/README.md) — архитектурные решения.
- [Архив](archive/README.md) — PRD v0.1 и milestones M1–M7 (исторические).
