# Архив

Исторические материалы. **Не** описывают текущий продукт — для этого см. [документацию](../README.md) и [README](../../README.md).

| Артефакт | Что это было |
|----------|----------------|
| [prd-v0.1.md](prd-v0.1.md) | Черновик ТЗ (2026-09). Часть идей реализована иначе; актуальный контракт — ADR + CLI/`--help`. |
| [milestones/](milestones/) | Acceptance criteria M1–M7 (все Done). Полезны как контекст решений в ADR. |

## Удалённые spikes

Закрытые исследовательские заметки (`docs/spikes/*`, bake-off protocol/plan, локальный `.bakeoff/`) удалены: выводы перенесены в ADR.

| Тема | Куда смотреть |
|------|----------------|
| ibcmd `--extension` / ibsrv argv | [ADR-023](../adr/023-multi-config-extensions.md), [ADR-025](../adr/025-publish-backends.md), issue [#84](https://github.com/pila86/1c-dev/issues/84) |
| YaXUnit RunUnitTests | [ADR-029](../adr/029-test-api.md), issue [#119](https://github.com/pila86/1c-dev/issues/119) |
| HTTP Debug Protocol (`dbgs`) | [ADR-031](../adr/031-debug-api-http.md), issue [#135](https://github.com/pila86/1c-dev/issues/135) |
| EDT adapter / write bake-off | [ADR-032](../adr/032-edt-source-adapter.md), [ADR-007](../adr/007-metadata-ir.md) |
| Ref-типы для агентов | UX в CLI/MCP + [ADR-011](../adr/011-metadata-ir-v1.md) |
