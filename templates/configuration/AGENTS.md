# 1C Development Rules

1. Never modify generated artifacts.
2. Respect the configured source format.
3. Never manually export configuration through Designer.
4. Use metadata tools for metadata operations.
5. Do not invent platform APIs.
6. Use documentation tools for unfamiliar platform APIs.
7. Run static checks after relevant changes.
8. Build and run relevant tests before declaring a task complete.
9. Prefer debugger for reproducible runtime failures.
10. Review semantic diff before completion.
11. For project init, metadata list/get/find/create/update/delete, build, and
    check prefer 1c-dev MCP tools (`project.init`, `metadata.list`,
    `metadata.get`, `metadata.find`, `metadata.create`, `metadata.update`,
    `metadata.delete`, `build`, `check`) — do not use shell or
    Designer/Configurator for these steps.
