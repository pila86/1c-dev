# Roadmap

## Текущий фокус: M2

**M2: metadata API** — list/get/find, update, create (Document, registers, …), delete.

→ [Acceptance criteria](milestones/m2-metadata-api.md)  
→ [GitHub milestone M2](https://github.com/pila86/1c-dev/milestone/2)

## Этапы

| Milestone | Цель | Статус |
|-----------|------|--------|
| **M1** | Init → metadata.create(Catalog) → build → check через MCP | Done |
| **M2** | Metadata API: list/get/find + update + create (Document, registers, …) + delete | In progress |
| M3 | Source formats: EDT adapter + import из `.cf` → один API на XML/EDT | Planned |
| M4 | Tests (YAxUnit), docs index, BSL integration | Planned |
| M5 | Debug (DAP), semantic diff, verify | Planned |
| M6 | Remote runtime, Docker, lockfile | Planned |

Документы этапов: [M1](milestones/m1-catalog-via-agent.md) · [M2](milestones/m2-metadata-api.md) · [M3](milestones/m3-source-formats.md)

## Принципы (из PRD)

- Agent-independent, IDE-independent, source-format-independent
- Reuse-first: BSL LS, MDClasses, ibcmd, существующие test runners
- Machine-readable first: JSON output, structured diagnostics
- Semantic-first: metadata IR, не сырой XML для агента

## Ссылки

- [PRD v0.1](../1c-dev-runtime-PRD-v0.1.md)
- [ADR](adr/README.md)
