# Roadmap

## Текущий фокус

**M6: Debug** — **Done** (GitHub milestone [M6](https://github.com/pila86/1c-dev/milestone/6) closed; PR [#146](https://github.com/pila86/1c-dev/pull/146)). HTTP Debug Protocol → CLI/MCP `debug.*` + `test.* --debug`/`test.wait` (#144, #147). Документ: [m6-debug](milestones/m6-debug.md).

**Follow-ups (вне milestone):**
- [#143](https://github.com/pila86/1c-dev/issues/143) — `ide configure` DAP `launch.json` hint
- [#128](https://github.com/pila86/1c-dev/issues/128) — Vanessa adapter (M5)

**Черновик next (не номер milestone):** Source formats (EDT) — write path выбран bake-off’ом (**D**: md-sparrow `.mdo` + `1cedtcli` export). Документы: [draft-source-formats](milestones/draft-source-formats.md), [draft-write-backend-bakeoff](milestones/draft-write-backend-bakeoff.md) (**Done** 2026-11-05).

→ [M6 Debug](milestones/m6-debug.md)  
→ [GitHub milestone M6](https://github.com/pila86/1c-dev/milestone/6)  
→ [Acceptance criteria M5](milestones/m5-tests.md)  
→ [M4 project model](milestones/m4-project-model.md)

## Этапы

| Milestone | Цель | Статус |
|-----------|------|--------|
| **M1** | Init → metadata.create(Catalog) → build → check через MCP | Done |
| **M2** | Metadata API: list/get/find + update + create (Document, registers, …) + delete | Done |
| **M3** | Product adopt: import `.cf`, user install/PATH **+ автозагрузка toolchain**, `ide configure`, BSL LS MCP, docs/context; **should (temporary):** metadata types coverage | Done |
| **M4** | Project home `.1c-dev/`, multi-config + extensions, platform templates, publish (ibsrv / webinst), `runtimes[]` | Done |
| **M5** | Test API: YAxUnit adapter, CLI/MCP `test.*`, `configurations[].tests`; Vanessa — follow-up | Done |
| **M6** | Debug API: HTTP Debug Protocol (`dbgs`), CLI/MCP `debug.*` + `test.* --debug`; DAP для IDE — reuse | Done |

Документы этапов: [M1](milestones/m1-catalog-via-agent.md) · [M2](milestones/m2-metadata-api.md) · [M3](milestones/m3-product-adopt.md) · [M4](milestones/m4-project-model.md) · [M5](milestones/m5-tests.md) · [M6](milestones/m6-debug.md)

## Черновики (вне нумерации)

Темы вне активного roadmap; файлы сохранены без номера milestone:

| Черновик | Было | Статус | Документ |
|----------|------|--------|----------|
| Write-backend bake-off | — | **Done** 2026-11-05 (XML=A, EDT=D) | [draft-write-backend-bakeoff](milestones/draft-write-backend-bakeoff.md) · [protocol](spikes/write-backend-bakeoff-protocol.md) |
| Source formats (EDT) | M4 EDT | Draft — next candidate; write=D | [draft-source-formats](milestones/draft-source-formats.md) |

Remote (Docker, lockfile) — при появлении текста как `draft-remote.md`.

## Принципы (из PRD)

- Agent-independent, IDE-independent, source-format-independent
- Reuse-first: BSL LS, MDClasses, ibcmd, bsl-context, test runners, HTTP debug / DAP adapters
- Machine-readable first: JSON output, structured diagnostics
- Semantic-first: metadata IR, не сырой XML для агента

## Ссылки

- [PRD v0.1](../1c-dev-runtime-PRD-v0.1.md)
- [ADR](adr/README.md)
