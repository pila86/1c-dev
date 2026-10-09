# Roadmap

## Текущий фокус: M6 Debug

**M6: Debug** — Planned: HTTP Debug Protocol → CLI/MCP `debug.*`; DAP только для IDE (reuse внешнего adapter). Документ: [m6-debug](milestones/m6-debug.md).

**M5: Tests** закрыт: Test API (YAxUnit), CLI/MCP `test.*`, `configurations[].tests`, runner cache + ensure, acceptance E2E (#129). Vanessa adapter — follow-up [#128](https://github.com/pila86/1c-dev/issues/128).

**M4: Project home, multi-config, templates, publish** закрыт: якорь `.1c-dev/`, несколько конфигураций и расширений, `runtimes[]`, tmplts, publish (ibsrv / webinst), acceptance E2E (#96).

→ [M6 Debug](milestones/m6-debug.md)  
→ [GitHub milestone M6](https://github.com/pila86/1c-dev/milestone/6)  
→ [Acceptance criteria M5](milestones/m5-tests.md)  
→ [M4 project model](milestones/m4-project-model.md)  
→ [GitHub milestone M5](https://github.com/pila86/1c-dev/milestone/5)  
→ [GitHub milestone M4](https://github.com/pila86/1c-dev/milestone/4)

## Этапы

| Milestone | Цель | Статус |
|-----------|------|--------|
| **M1** | Init → metadata.create(Catalog) → build → check через MCP | Done |
| **M2** | Metadata API: list/get/find + update + create (Document, registers, …) + delete | Done |
| **M3** | Product adopt: import `.cf`, user install/PATH **+ автозагрузка toolchain**, `ide configure`, BSL LS MCP, docs/context; **should (temporary):** metadata types coverage | Done |
| **M4** | Project home `.1c-dev/`, multi-config + extensions, platform templates, publish (ibsrv / webinst), `runtimes[]` | Done |
| **M5** | Test API: YAxUnit adapter, CLI/MCP `test.*`, `configurations[].tests`; Vanessa — follow-up | Done |
| **M6** | Debug API: HTTP Debug Protocol (`dbgs`), CLI/MCP `debug.*`; DAP для IDE — reuse | Planned |

Документы этапов: [M1](milestones/m1-catalog-via-agent.md) · [M2](milestones/m2-metadata-api.md) · [M3](milestones/m3-product-adopt.md) · [M4](milestones/m4-project-model.md) · [M5](milestones/m5-tests.md) · [M6](milestones/m6-debug.md)

## Черновики (вне нумерации)

Темы вне активного roadmap; файлы сохранены без номера milestone:

| Черновик | Было | Документ |
|----------|------|----------|
| Source formats (EDT) | M4 EDT | [draft-source-formats](milestones/draft-source-formats.md) |

Remote (Docker, lockfile) — при появлении текста как `draft-remote.md`.

## Принципы (из PRD)

- Agent-independent, IDE-independent, source-format-independent
- Reuse-first: BSL LS, MDClasses, ibcmd, bsl-context, test runners, HTTP debug / DAP adapters
- Machine-readable first: JSON output, structured diagnostics
- Semantic-first: metadata IR, не сырой XML для агента

## Ссылки

- [PRD v0.1](../1c-dev-runtime-PRD-v0.1.md)
- [ADR](adr/README.md)
