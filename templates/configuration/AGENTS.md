# 1C Development Rules

1. Never modify generated artifacts.
2. Respect the configured source format.
3. Never manually export configuration through Designer.
4. Use metadata tools for metadata operations.
5. Do not invent platform APIs.
6. Use documentation tools (`docs.search` / `docs.get`) for unfamiliar platform APIs.
7. Run static checks after relevant changes.
8. Build and run relevant tests before declaring a task complete.
9. Prefer debugger for reproducible runtime failures.
10. Review semantic diff before completion.
11. Prefer MCP tools over shell or Designer/Configurator:
    - **1c-dev** MCP: project init/import/clean, ide.configure, metadata list/get/find/create/update/delete,
      build, check, runtime.start/stop/status (client thick|thin, optional debug=/Debug),
      and docs.* when available.
      `project.clean` is destructive (wipes source + `.1c-dev/runtime/`); always pass yes=true
      and confirm intent first — does not touch `.1c-dev/project.yaml` / AGENTS.md / IDE MCP / git.
      MCP `path` = scope root (parent of `.1c-dev`).
      Write types for metadata.create/update/delete: 23 Meta DSL + Subsystem
      (AccountingRegister, AccumulationRegister, BusinessProcess, CalculationRegister,
      Catalog, ChartOfAccounts, ChartOfCalculationTypes, ChartOfCharacteristicTypes,
      CommonModule, Constant, DataProcessor, DefinedType, Document, DocumentJournal,
      Enum, EventSubscription, ExchangePlan, HTTPService, InformationRegister, Report,
      ScheduledJob, Subsystem, Task, WebService) — see `doctor` → `supportedTypes`.
    - **bsl-language-server** MCP: BSL code analysis (diagnostics, symbols, references,
      hover, definitions) — not for metadata or build.
      Before analyze_file / hover / definition / etc.: call `list_workspace_folders`;
      if the project root is missing, call `register_workspace_folder` with the IDE
      workspace root (not `src/cf`). Then analyze files inside that folder.
