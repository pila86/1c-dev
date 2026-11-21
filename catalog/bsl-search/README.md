# bsl-search

Recipe для [axel-avb/mcp-bsl-search](https://github.com/axel-avb/mcp-bsl-search)
(ADR-033 Этап 3 / #175).

## Что поднимает 1c-dev

| Сервис | Host port (default) | Назначение |
|--------|---------------------|------------|
| Elasticsearch 8.15 | `19200` | индекс `bsl-methods` (BM25) |
| search-api | `18080` | HTTP search API |
| mcp-server | `18005` | MCP Streamable HTTP `/mcp` |

App-образы **собираются из git** upstream (pin `source.ref` в `tool.yaml`).

## UX

```bash
1c-dev tools install bsl-search   # clone upstream + download HF corpus
1c-dev services up bsl-search     # build/up + bulk-load JSONL → ES
1c-dev ide configure
```

При install скачивается `units_curated.jsonl` из
[`pupkaZALUPKA/1c-bsl-dataset`](https://huggingface.co/datasets/pupkaZALUPKA/1c-bsl-dataset)
(~1.4 GB). `HF_TOKEN` не обязателен для публичного датасета.

Данные: `~/.local/share/1c-dev/data/bsl-search/`.

## BM25 сейчас; inference позже

По умолчанию `EMBEDDING_URL` / `RERANKER_URL` пустые — поиск BM25.

Подключить локальный или внешний сервис:

1. Прописать URL (и ключи) в `~/.local/share/1c-dev/tools/bsl-search/.env`
2. `1c-dev services restart bsl-search`

**Reranker** улучшает выдачу сразу (по тексту топ-кандидатов).  
**kNN / embedding** требуют векторов в ES — отдельный `embed_index` или dump с embeddings
(не входит в Этап 3).

## Preflight / diagnostics

- Нет Docker / git → `1CX003` / `1CX007`
- HF download fail → `1CX006`
- ES unhealthy / пустой индекс после up → `1CX005` + suggestion
- Принудительный reindex: `BSL_SEARCH_REINDEX=1` в `.env`, затем `services up`

## Knowledge (ITS/Habr)

Индекс `bsl-knowledge` в Этапе 3 не заполняется автоматически.
Код-поиск по `bsl-methods` достаточен для MVP.
