# Roadmap

## Текущий фокус: M5

**M4: Project home, multi-config, templates, publish** закрыт: якорь `.1c-dev/`, несколько конфигураций и расширений, `runtimes[]`, tmplts, publish (ibsrv / webinst), acceptance E2E (#96).

**M5: Tests** — Test API: YAxUnit adapter, CLI/MCP `test.*`, `configurations[].tests`; Vanessa — follow-up.

→ [Acceptance criteria M5](milestones/m5-tests.md)  
→ [M4 project model](milestones/m4-project-model.md)  
→ [GitHub milestone M4](https://github.com/pila86/1c-dev/milestone/4)

## Этапы

| Milestone | Цель | Статус |
|-----------|------|--------|
| **M1** | Init → metadata.create(Catalog) → build → check через MCP | Done |
| **M2** | Metadata API: list/get/find + update + create (Document, registers, …) + delete | Done |
| **M3** | Product adopt: import `.cf`, user install/PATH **+ автозагрузка toolchain**, `ide configure`, BSL LS MCP, docs/context; **should (temporary):** metadata types coverage | Done |
| **M4** | Project home `.1c-dev/`, multi-config + extensions, platform templates, publish (ibsrv / webinst), `runtimes[]` | Done |
| **M5** | Test API: YAxUnit adapter, CLI/MCP `test.*`, `configurations[].tests`; Vanessa — follow-up | Planned |

Документы этапов: [M1](milestones/m1-catalog-via-agent.md) · [M2](milestones/m2-metadata-api.md) · [M3](milestones/m3-product-adopt.md) · [M4](milestones/m4-project-model.md) · [M5](milestones/m5-tests.md)

## Черновики (вне нумерации)

Темы вне активного roadmap; файлы сохранены без номера milestone:

| Черновик | Было | Документ |
|----------|------|----------|
| Source formats (EDT) | M4 EDT | [draft-source-formats](milestones/draft-source-formats.md) |

Debug (DAP) / Remote (Docker, lockfile) — при появлении текстов сразу как `draft-debug.md` / `draft-remote.md`.

## Принципы (из PRD)

- Agent-independent, IDE-independent, source-format-independent
- Reuse-first: BSL LS, MDClasses, ibcmd, bsl-context, существующие test runners
- Machine-readable first: JSON output, structured diagnostics
- Semantic-first: metadata IR, не сырой XML для агента

## Ссылки

- [PRD v0.1](../1c-dev-runtime-PRD-v0.1.md)
- [ADR](adr/README.md)
