# 1C Development Rules (extension)

1. Never modify generated artifacts.
2. Respect the configured source format.
3. Never manually export configuration through Designer.
4. Use metadata tools for metadata operations.
5. Do not invent platform APIs.
6. Use documentation tools (`docs.search` / `docs.get`) for unfamiliar platform APIs.
7. Run static checks after relevant changes.
8. Build and run relevant tests before declaring a task complete.
9. Prefer MCP tools over shell or Designer/Configurator:
    - **1c-dev** MCP: project.*, metadata.*, build, check, runtime.*, extension.list, docs.*.
      MCP `path` = scope root (parent of `.1c-dev`).
      `build` loads nested extensions into the selected runtime IB after the configuration.
    - **bsl-language-server** MCP: BSL code analysis — not for metadata or build.
