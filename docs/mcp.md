# MCP для AI-агентов

`1c-dev mcp` — stdio MCP-сервер. Конфиги пишет `init` / `ide configure` ([ADR-010](adr/010-mcp-architecture.md), [ADR-016](adr/016-ide-configure.md)).

Слои продукта и зависимости: [explanation/overview.md](explanation/overview.md).

## Подключение

Пример `.cursor/mcp.json` (то же в `.kilo/mcp.json` для Kilocode):

```json
{
  "mcpServers": {
    "1c-dev": {
      "command": "1c-dev",
      "args": ["mcp"]
    }
  }
}
```

Poetry-checkout: `"command": "poetry"`, `"args": ["run", "1c-dev", "mcp"]`.

Дополнительно IDE может получить MCP внешних tools (`bsl-ls`, `v8std`, …) после `tools install` + `services up` + `ide configure` ([ADR-033](adr/033-external-tools-manager.md)).

## Tools

### Проект / конфигурация

`project.get`, `project.list`, `project.init`, `project.clean`,
`configuration.add`, `configuration.import`, `configuration.list`, `configuration.get`,
`configuration.remove`, `configuration.set-default`,
`extension.add`, `extension.list`,
`templates.roots`, `templates.list`, `templates.get`,
`ide.configure`, `source.convert`

### Metadata / build

`metadata.list`, `metadata.get`, `metadata.find`,
`metadata.create`, `metadata.update`, `metadata.delete`,
`build`, `check`

### Runtime / publish / docs

`runtime.start`, `runtime.stop`, `runtime.status`,
`publish.up`, `publish.down`, `publish.status`, `publish.url`,
`docs.search`, `docs.get`

### Test / debug

`test.discover`, `test.list`, `test.run`, `test.runOne`, `test.wait`, `test.report`,
`debug.server.start` / `stop` / `status`,
`debug.attach`, `debug.detach`, `debug.forceDetach`,
`debug.breakpoint`, `debug.clearBreakpoints`,
`debug.wait`, `debug.continue`, `debug.stepIn`, `debug.stepOver`, `debug.stepOut`,
`debug.pause`, `debug.stack`, `debug.variables`, `debug.evaluate`,
`debug.targets`, `debug.status`, `debug.reloadMetadata`

`project.clean` — destructive (`yes=true`); не трогает манифест / IDE / git.

Ссылочные типы в `metadata.create` / `update`: `type: "Ref"`, `reference: "Catalog.Name"` — не `CatalogRef.*`.
