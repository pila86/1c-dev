"""MCP stdio server: patterns.search / get / feedback."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from patterns_knowledge import feedback as fb
from patterns_knowledge import index as idx

server = FastMCP(
    "patterns-knowledge",
    instructions=(
        "Coding patterns for 1C:Enterprise BSL. "
        "Use patterns.search for a task description, then patterns.get for full recipe. "
        "Not for platform API lookup (use docs) or project build (use 1c-dev)."
    ),
)


@server.tool(name="patterns.search")
def patterns_search(
    query: str,
    task: str | None = None,
    limit: int = 3,
) -> dict[str, Any]:
    """Search coding pattern cards by natural-language task description.

    Optional task/subdomain filter examples: document_posting, accumulation_register,
    transactions_locks, strings_nstr, queries, forms_client_server, bsp_ssl.
    Returns up to `limit` short hits (default 3). Call patterns.get for full body/code.
    """
    hits = idx.search(query, task=task, limit=limit)
    return {"hits": hits}


@server.tool(name="patterns.get")
def patterns_get(id: str) -> dict[str, Any]:
    """Return full coding pattern card by id from patterns.search."""
    card = idx.get_card(id)
    if card is None:
        return {"error": "not_found", "id": id}
    return card


@server.tool(name="patterns.feedback")
def patterns_feedback(id: str, vote: int, note: str | None = None) -> dict[str, Any]:
    """Local +1 / -1 feedback for a card (stored under .patterns-ab/)."""
    _ = note
    try:
        return fb.vote(id, int(vote))
    except ValueError as e:
        return {"error": str(e)}


def run() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    run()
