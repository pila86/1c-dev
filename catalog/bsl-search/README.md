# bsl-search (scaffold)

Recipe для [axel-avb/mcp-bsl-search](https://github.com/axel-avb/mcp-bsl-search).

**Статус:** scaffold Этапа 3 (ADR-033 / #175). Не production-ready:
образы `REPLACE_ME`, preflight ES ещё не вшит в `services up`.

## Профиль `app` (MVP)

1c-dev поднимает только:

- `mcp-server` (MCP Streamable HTTP, default host port `18005`)
- `search-api` (localhost `18080`)

Пользователь даёт:

| Переменная | Назначение |
|---|---|
| `ELASTICSEARCH_URL` | ES с индексами методов / knowledge |
| `EMBEDDING_URL` | сервис эмбеддингов |
| `RERANKER_URL` | reranker |

См. upstream `.env.example` и `DEPLOY.md`.

## Restore индекса

Полный offline dump / embed pipeline **не** входит в scaffold и Этап 3 MVP.
Ожидается:

1. Поднять Elasticsearch (внешне или позже профиль `full` — Этап 6).
2. Восстановить индексы `bsl-methods-full` / `bsl-knowledge` по документации upstream
   (`indexer/`, `DEPLOY.md`) — без авто-embed со стороны 1c-dev.
3. Прописать URL в установленном `.env`:
   `~/.local/share/1c-dev/tools/bsl-search/.env`

Диагностика «ES unreachable / index missing» — в полной реализации Этапа 3
(не silent fail).

## UX (когда будет готово)

```bash
1c-dev tools install bsl-search   # после pin образов
# отредактировать .env: ELASTICSEARCH_URL, EMBEDDING_URL, RERANKER_URL
1c-dev services up bsl-search
1c-dev ide configure
```

Сейчас `tools install` материализует scaffold с warning по pin’ам;
`services up` без валидных образов завершится ошибкой compose.

## Labels

Compose-сервисы помечены `managed-by=1c-dev` / `com.1c-dev.tool=bsl-search`
(контракт Service Manager Этапа 2).
