# bsl-ls (shared BSL Language Server MCP)

Recipe для [1c-syntax/bsl-language-server](https://github.com/1c-syntax/bsl-language-server)
в режиме Streamable HTTP — **один процесс на машину**, несколько проектов
регистрируют workspace folders через MCP tools.

## UX

```bash
1c-dev tools install bsl-ls    # jar 1.1.0-rc.9 → share
1c-dev services up bsl-ls      # java -jar … mcp --protocol streamable
1c-dev ide configure           # mcpServers.bsl-language-server → url
```

Default MCP: `http://127.0.0.1:18767/mcp`.

Override jar: `ONEC_BSLLS_JAR=/path/to.jar` или правка `BSLLS_JAR` в
`~/.local/share/1c-dev/tools/bsl-ls/.env`.

## Почему не stable 1.0.7

Нужен MCP `register_workspace_folder` ([#4462](https://github.com/1c-syntax/bsl-language-server/pull/4462)),
доступный в линии `1.1.0-rc`. Pin: `1.1.0-rc.9`.
