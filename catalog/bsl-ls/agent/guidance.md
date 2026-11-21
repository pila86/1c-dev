### Optional MCP: bsl-language-server (shared)

Когда MCP `bsl-language-server` доступен в сессии:

- Используй его для BSL-анализа, diagnostics, type/member lookup по workspace.
- Сначала `list_workspace_folders`; нет корня — `register_workspace_folder` на **корень IDE**
  (не `src/cf`). Вызовы с `fileType=BSL`.
- Инстанс **общий на машину**: не вызывай `unregister_workspace_folder` для чужих проектов.

Когда не использовать:

- Вместо `docs.*` для языка запросов / конструкций языка.
- Вместо `metadata.*` / build / check / test / debug.
- Если MCP недоступен — не invent API и не притворяйся, что вызвал tool;
  подскажи `1c-dev services up bsl-ls`.
