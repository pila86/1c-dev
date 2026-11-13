"""CLI: ingest / reindex / search / get / mcp."""

from __future__ import annotations

import json
from typing import Optional

import typer

app = typer.Typer(
    name="patterns-knowledge",
    help="Spike: coding patterns knowledge (ingest, index, MCP).",
    no_args_is_help=True,
)


@app.command()
def ingest(
    source: Optional[str] = typer.Option(None, help="Only this sources.yaml id"),
    force: bool = typer.Option(False, help="Wipe cards and rebuild"),
) -> None:
    """Clone allowlist and write Card JSON under .patterns-ab/cards/."""
    from patterns_knowledge.ingest import ingest as do_ingest

    stats = do_ingest(source_id=source, force=force)
    typer.echo(json.dumps(stats, ensure_ascii=False, indent=2))


@app.command()
def reindex(
    full: bool = typer.Option(False, help="Force full rebuild flag in meta"),
) -> None:
    """Build semantic/TF-IDF index from cards."""
    from patterns_knowledge.index import reindex as do_reindex

    meta = do_reindex(full=full)
    typer.echo(json.dumps(meta, ensure_ascii=False, indent=2))


@app.command("search")
def search_cmd(
    query: str = typer.Argument(...),
    task: Optional[str] = typer.Option(None),
    limit: int = typer.Option(3),
) -> None:
    from patterns_knowledge.index import search

    hits = search(query, task=task, limit=limit)
    typer.echo(json.dumps({"hits": hits}, ensure_ascii=False, indent=2))


@app.command()
def get(card_id: str = typer.Argument(..., metavar="ID")) -> None:
    from patterns_knowledge.index import get_card

    card = get_card(card_id)
    if card is None:
        typer.echo(json.dumps({"error": "not_found", "id": card_id}))
        raise typer.Exit(1)
    typer.echo(json.dumps(card, ensure_ascii=False, indent=2))


@app.command()
def mcp() -> None:
    """Run MCP server on stdio."""
    from patterns_knowledge.mcp_server import run

    run()


@app.command()
def transcript(
    jsonl: str = typer.Argument(
        ...,
        help="Path to agent.jsonl (or run dir containing it)",
    ),
    watch: bool = typer.Option(False, "--watch", help="Rewrite while jsonl grows"),
    text_only: bool = typer.Option(
        False, "--text-only", help="Only model text, no tool lines"
    ),
) -> None:
    """Build agent.transcript.md from OpenCode JSONL (readable model output)."""
    from pathlib import Path

    from patterns_knowledge.transcript import watch_transcript, write_transcript

    p = Path(jsonl)
    if p.is_dir():
        p = p / "agent.jsonl"
    if not p.is_file() and not watch:
        typer.echo(json.dumps({"error": "not_found", "path": str(p)}))
        raise typer.Exit(1)
    out = p.with_name("agent.transcript.md")
    include_tools = not text_only
    if watch:
        typer.echo(f"watching {p} → {out}")
        watch_transcript(p, out, include_tools=include_tools)
    else:
        write_transcript(p, out, include_tools=include_tools)
        typer.echo(str(out))


@app.command("agent-run")
def agent_run(
    run_dir: str = typer.Argument(..., help="Run root .patterns-ab/runs/A-…"),
    model: Optional[str] = typer.Option(None, "--model", "-m"),
) -> None:
    """OpenCode run with live agent.jsonl + agent.transcript.md."""
    from pathlib import Path

    from patterns_knowledge.run_agent import execute_agent_run

    try:
        code = execute_agent_run(Path(run_dir), model=model)
    except (FileNotFoundError, ValueError) as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(2) from e
    raise typer.Exit(code)


def run() -> None:
    app()


if __name__ == "__main__":
    run()
