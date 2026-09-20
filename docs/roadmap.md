# Roadmap

## Текущий фокус: M2

**M2: metadata API** — list/get/find, update, create (Document, registers, …), delete.

После M2 — **M3 Product adopt**: поставить CLI в PATH, импортировать `.cf`, подключить агента в IDE (в т.ч. BSL LS MCP и docs через bsl-context).

→ [Acceptance criteria M2](milestones/m2-metadata-api.md)  
→ [GitHub milestone M2](https://github.com/pila86/1c-dev/milestone/2)  
→ [M3 Product adopt](milestones/m3-product-adopt.md)

## Этапы

| Milestone | Цель | Статус |
|-----------|------|--------|
| **M1** | Init → metadata.create(Catalog) → build → check через MCP | Done |
| **M2** | Metadata API: list/get/find + update + create (Document, registers, …) + delete | In progress |
| **M3** | Product adopt: import `.cf`, user install/PATH **+ автозагрузка toolchain** (xml-gen, md-reader/MDClasses, …), `setup` (IDE/agents/MCP), BSL LS MCP wiring, docs/context (bsl-context) | Planned |
| M4 | Source formats: EDT adapter + `source.convert` XML ↔ EDT | Planned |
| M5 | Tests (YAxUnit / Vanessa) | Planned |
| M6 | Debug (DAP), semantic diff, verify | Planned |
| M7 | Remote runtime, Docker, lockfile | Planned |

Документы этапов: [M1](milestones/m1-catalog-via-agent.md) · [M2](milestones/m2-metadata-api.md) · [M3](milestones/m3-product-adopt.md) · [M4](milestones/m4-source-formats.md)

## Принципы (из PRD)

- Agent-independent, IDE-independent, source-format-independent
- Reuse-first: BSL LS, MDClasses, ibcmd, bsl-context, существующие test runners
- Machine-readable first: JSON output, structured diagnostics
- Semantic-first: metadata IR, не сырой XML для агента

## Ссылки

- [PRD v0.1](../1c-dev-runtime-PRD-v0.1.md)
- [ADR](adr/README.md)
