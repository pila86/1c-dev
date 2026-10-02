# Roadmap

## Текущий фокус: M4

**M3: Product adopt** закрыт: `uv tool` + toolchain, import `.cf`, `ide configure`, BSL LS MCP, docs (bsl-context), acceptance E2E (#52).

**M4: Project home, multi-config, templates, publish** — якорь `.1c-dev/`, несколько конфигураций и расширений, `runtimes[]`, каталог шаблонов платформы, публикация (ibsrv / Apache). Issues [#84](https://github.com/pila86/1c-dev/issues/84)–[#96](https://github.com/pila86/1c-dev/issues/96).

→ [Acceptance criteria M4](milestones/m4-project-model.md)  
→ [GitHub milestone M4](https://github.com/pila86/1c-dev/milestone/4)  
→ [M3 product adopt](milestones/m3-product-adopt.md)

## Этапы

| Milestone | Цель | Статус |
|-----------|------|--------|
| **M1** | Init → metadata.create(Catalog) → build → check через MCP | Done |
| **M2** | Metadata API: list/get/find + update + create (Document, registers, …) + delete | Done |
| **M3** | Product adopt: import `.cf`, user install/PATH **+ автозагрузка toolchain**, `ide configure`, BSL LS MCP, docs/context; **should (temporary):** metadata types coverage | Done |
| **M4** | Project home `.1c-dev/`, multi-config + extensions, platform templates, publish (ibsrv / webinst), `runtimes[]` | In progress |
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
