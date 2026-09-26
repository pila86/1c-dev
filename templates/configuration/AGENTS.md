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
    - **1c-dev** MCP: project init/import, ide.configure, metadata list/get/find/create/update/delete,
      build, check, and docs.* when available.
    - **bsl-language-server** MCP: BSL code analysis (diagnostics, symbols, references,
      hover, definitions) — not for metadata or build.
      Before analyze_file / hover / definition / etc.: call `list_workspace_folders`;
      if the project root is missing, call `register_workspace_folder` with the IDE
      workspace root (not `src/cf`). Then analyze files inside that folder.
