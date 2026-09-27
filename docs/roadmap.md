# Roadmap

## Текущий фокус: M4

**M3: Product adopt** закрыт: `uv tool` + toolchain, import `.cf`, `ide configure`, BSL LS MCP, docs (bsl-context), acceptance E2E (#52).

**M4: Source formats** — EDT adapter + `source.convert` XML ↔ EDT.

→ [Acceptance criteria M4](milestones/m4-source-formats.md)  
→ [M3 product adopt](milestones/m3-product-adopt.md)  
→ [GitHub milestone M3](https://github.com/pila86/1c-dev/milestone/3)

## Этапы

| Milestone | Цель | Статус |
|-----------|------|--------|
| **M1** | Init → metadata.create(Catalog) → build → check через MCP | Done |
| **M2** | Metadata API: list/get/find + update + create (Document, registers, …) + delete | Done |
| **M3** | Product adopt: import `.cf`, user install/PATH **+ автозагрузка toolchain** (xml-gen, md-reader/MDClasses, …), `ide configure` (IDE/agents/MCP), BSL LS MCP wiring, docs/context (bsl-context); **should (temporary):** metadata types coverage (трек E — 23 meta + Subsystem) | Done |
| M4 | Source formats: EDT adapter + `source.convert` XML ↔ EDT | Planned |
| M5 | Tests (YAxUnit / Vanessa) | Planned (draft) |
| M6 | Debug (DAP), semantic diff, verify; attach к клиенту после `runtime.start --debug` (ADR-019) | Planned |
| M7 | Remote runtime, Docker, lockfile | Planned |

Документы этапов: [M1](milestones/m1-catalog-via-agent.md) · [M2](milestones/m2-metadata-api.md) · [M3](milestones/m3-product-adopt.md) · [M4](milestones/m4-source-formats.md) · [M5](milestones/m5-tests.md)

## Принципы (из PRD)

- Agent-independent, IDE-independent, source-format-independent
- Reuse-first: BSL LS, MDClasses, ibcmd, bsl-context, существующие test runners
- Machine-readable first: JSON output, structured diagnostics
- Semantic-first: metadata IR, не сырой XML для агента

## Ссылки

- [PRD v0.1](../1c-dev-runtime-PRD-v0.1.md)
- [ADR](adr/README.md)
