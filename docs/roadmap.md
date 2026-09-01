# Roadmap

## Текущий фокус: M1

**M1: catalog via agent** — агент через MCP создаёт конфигурацию с одним справочником.

→ [Acceptance criteria](milestones/m1-catalog-via-agent.md)  
→ [GitHub milestone](https://github.com/pila86/1c-dev/milestone/1) · [Issues #1–#10](https://github.com/pila86/1c-dev/issues?q=milestone%3A%22M1%3A+catalog+via+agent%22)

## Этапы

| Milestone | Цель | Статус |
|-----------|------|--------|
| **M1** | Init → metadata.create(Catalog) → build → check через MCP | In progress |
| M2 | Metadata read-only: list / get / find | Planned |
| M3 | EDT adapter — один API на XML и EDT | Planned |
| M4 | Tests (YAxUnit), docs index, BSL integration | Planned |
| M5 | Debug (DAP), semantic diff, verify | Planned |
| M6 | Remote runtime, Docker, lockfile | Planned |

## Принципы (из PRD)

- Agent-independent, IDE-independent, source-format-independent
- Reuse-first: BSL LS, MDClasses, ibcmd, существующие test runners
- Machine-readable first: JSON output, structured diagnostics
- Semantic-first: metadata IR, не сырой XML для агента

## Ссылки

- [PRD v0.1](../1c-dev-runtime-PRD-v0.1.md)
- [ADR](adr/README.md)
