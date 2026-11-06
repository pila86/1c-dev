# Roadmap

## Текущий фокус

**M7: Source formats (EDT)** — Planned ([GitHub milestone M7](https://github.com/pila86/1c-dev/milestone/7)). Полный паритет с XML (**B**): EDT Source Adapter + semantic write (**D**: md-sparrow `.mdo` + `1cedtcli` export) + `source.convert`. Документ: [m7-source-formats](milestones/m7-source-formats.md). Волна 0 Done: spike [#149](https://github.com/pila86/1c-dev/issues/149); волна 1 — ADR [#150](https://github.com/pila86/1c-dev/issues/150) Done ([ADR-032](adr/032-edt-source-adapter.md)); doctor [#151](https://github.com/pila86/1c-dev/issues/151) Done; волна 2 — [#152](https://github.com/pila86/1c-dev/issues/152) Done (`EdtSourceAdapter` detect/read); [#153](https://github.com/pila86/1c-dev/issues/153) Done (pin md-sparrow + `apply-mutation`); волна 3 — [#154](https://github.com/pila86/1c-dev/issues/154) Done (`metadata.*` create/update/delete на `format: edt`); [#155](https://github.com/pila86/1c-dev/issues/155) Done (`build`/`check` EDT: `1cedtcli` export → ibcmd); волна 4 — [#156](https://github.com/pila86/1c-dev/issues/156) Done (`source.convert` XML ↔ EDT + манифест); [#157](https://github.com/pila86/1c-dev/issues/157) Done (MCP `source.convert`).

**Follow-ups (вне milestone):**
- [#143](https://github.com/pila86/1c-dev/issues/143) — `ide configure` DAP `launch.json` hint
- [#128](https://github.com/pila86/1c-dev/issues/128) — Vanessa adapter (M5)

**Закрыто недавно:** M6 Debug — Done ([m6-debug](milestones/m6-debug.md), PR [#146](https://github.com/pila86/1c-dev/pull/146)); write-backend bake-off — Done ([write-backend-bakeoff](spikes/write-backend-bakeoff.md), 2026-11-05).

→ [M7 Source formats](milestones/m7-source-formats.md)  
→ [GitHub milestone M7](https://github.com/pila86/1c-dev/milestone/7)  
→ [M6 Debug](milestones/m6-debug.md)

## Этапы

| Milestone | Цель | Статус |
|-----------|------|--------|
| **M1** | Init → metadata.create(Catalog) → build → check через MCP | Done |
| **M2** | Metadata API: list/get/find + update + create (Document, registers, …) + delete | Done |
| **M3** | Product adopt: import `.cf`, user install/PATH **+ автозагрузка toolchain**, `ide configure`, BSL LS MCP, docs/context; **should (temporary):** metadata types coverage | Done |
| **M4** | Project home `.1c-dev/`, multi-config + extensions, platform templates, publish (ibsrv / webinst), `runtimes[]` | Done |
| **M5** | Test API: YAxUnit adapter, CLI/MCP `test.*`, `configurations[].tests`; Vanessa — follow-up | Done |
| **M6** | Debug API: HTTP Debug Protocol (`dbgs`), CLI/MCP `debug.*` + `test.* --debug`; DAP для IDE — reuse | Done |
| **M7** | Source formats: EDT adapter + `source.convert` + metadata/build/check parity (write=D) | Planned |

Документы этапов: [M1](milestones/m1-catalog-via-agent.md) · [M2](milestones/m2-metadata-api.md) · [M3](milestones/m3-product-adopt.md) · [M4](milestones/m4-project-model.md) · [M5](milestones/m5-tests.md) · [M6](milestones/m6-debug.md) · [M7](milestones/m7-source-formats.md)

## Spikes / архив решений

| Тема | Статус | Документ |
|------|--------|----------|
| Write-backend bake-off | **Done** 2026-11-05 (XML=A, EDT=D) | [write-backend-bakeoff](spikes/write-backend-bakeoff.md) · [protocol](spikes/write-backend-bakeoff-protocol.md) |
| EDT fixture + `1cedtcli` smoke | **Done** 2026-11-06 | [149-edt-source-adapter](spikes/149-edt-source-adapter.md) · fixture `tests/fixtures/edt_spike` |

Remote (Docker, lockfile) — при появлении текста как `docs/milestones/draft-remote.md`.

## Принципы (из PRD)

- Agent-independent, IDE-independent, source-format-independent
- Reuse-first: BSL LS, MDClasses, ibcmd, bsl-context, test runners, HTTP debug / DAP adapters
- Machine-readable first: JSON output, structured diagnostics
- Semantic-first: metadata IR, не сырой XML для агента

## Ссылки

- [PRD v0.1](../1c-dev-runtime-PRD-v0.1.md)
- [ADR](adr/README.md)
