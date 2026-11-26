# Roadmap

## Сейчас

Продуктовые milestones **M1–M7 Done**. Актуальная работа — follow-ups и polish поверх стабильного CLI/MCP:

- External Tools Manager — [ADR-033](adr/033-external-tools-manager.md) (этапы 0–5, 7; этап 6 deferred)
- Smart init / adopt — [ADR-034](adr/034-smart-init-adopt.md)
- [#143](https://github.com/pila86/1c-dev/issues/143) — `ide configure` DAP `launch.json` hint
- [#128](https://github.com/pila86/1c-dev/issues/128) — Vanessa adapter (Test API)
- EDT write-gaps — [#166](https://github.com/pila86/1c-dev/issues/166)

Backlog: [GitHub Issues](https://github.com/pila86/1c-dev/issues) / [milestones](https://github.com/pila86/1c-dev/milestones).

## Идеи (не committed)

- Автономный агент в этом репо: OpenHands + платформа/EDT/Xvfb/VNC/`1c-dev` (HASP, draft MR) — [proposal](proposals/autonomous-agent-sandbox.md)

## Этапы (Done)

| Milestone | Цель | Документ |
|-----------|------|----------|
| **M1** | Init → metadata.create → build → check через MCP | [archive](archive/milestones/m1-catalog-via-agent.md) |
| **M2** | Metadata API: list/get/find + update/create/delete | [archive](archive/milestones/m2-metadata-api.md) |
| **M3** | Product adopt: import `.cf`, `uv tool`, IDE, docs | [archive](archive/milestones/m3-product-adopt.md) |
| **M4** | Project home, multi-config, extensions, publish | [archive](archive/milestones/m4-project-model.md) |
| **M5** | Test API (YAxUnit); Vanessa — follow-up | [archive](archive/milestones/m5-tests.md) |
| **M6** | Debug API (HTTP `dbgs`) | [archive](archive/milestones/m6-debug.md) |
| **M7** | EDT source + `source.convert` + write path D | [archive](archive/milestones/m7-source-formats.md) |

## Принципы

- Agent-independent, IDE-independent, source-format-independent
- Reuse-first: BSL LS, MDClasses, ibcmd, bsl-context, YAxUnit, HTTP debug
- Machine-readable first: JSON output, structured diagnostics
- Semantic-first: metadata IR, не сырой XML для агента

## Ссылки

- [Документация](README.md)
- [ADR](adr/README.md)
- [Архив PRD / milestones](archive/README.md)
