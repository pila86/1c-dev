"""CLI: 1c-dev docs …"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from cli.output import OutputFormat, OutputOption, resolve_output
from core.docs import DocsResult, get_docs, search_docs
from core.exit_codes import ENV_UNAVAILABLE, PROJECT_ERROR, SUCCESS

app = typer.Typer(
    name="docs",
    help="Локальный индекс синтакс-помощника платформы (bsl-context).",
    add_completion=False,
    no_args_is_help=True,
)


def _emit(payload: dict[str, Any], output: OutputFormat, *, text_lines: list[str]) -> None:
    if output is OutputFormat.json:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for line in text_lines:
            typer.echo(line)


def _error_text(result: DocsResult) -> list[str]:
    lines = ["status: error"]
    for diag in result.diagnostics:
        code = diag.get("code", "")
        prefix = f"[{code}] " if code else ""
        lines.append(f"error: {prefix}{diag.get('message', '')}")
        suggestion = diag.get("suggestion")
        if suggestion:
            lines.append(f"  → {suggestion}")
    return lines


def _exit_code(result: DocsResult) -> int:
    if result.status == "ok":
        return SUCCESS
    codes = {d.get("code") for d in result.diagnostics}
    if codes & {"1CX001", "1CX002"}:
        return ENV_UNAVAILABLE
    return PROJECT_ERROR


def _search_text(result: DocsResult) -> list[str]:
    if result.status != "ok":
        return _error_text(result)
    lines = ["status: ok"]
    if result.platform_version:
        lines.append(f"platformVersion: {result.platform_version}")
    if result.index_built:
        lines.append("index: built")
    for diag in result.diagnostics:
        if diag.get("severity") == "info":
            lines.append(f"info: {diag.get('message', '')}")
    if not result.hits:
        lines.append("hits: (none)")
        return lines
    lines.append("hits:")
    for hit in result.hits:
        name = hit.get("name", "")
        kind = hit.get("kind", "")
        snippet = hit.get("snippet") or ""
        line = f"  - {name} ({kind})"
        if snippet:
            line += f" — {snippet[:80]}"
        lines.append(line)
    return lines


def _get_text(result: DocsResult) -> list[str]:
    if result.status != "ok":
        return _error_text(result)
    lines = ["status: ok"]
    if result.platform_version:
        lines.append(f"platformVersion: {result.platform_version}")
    entry = result.entry or {}
    if entry.get("qualifiedName"):
        lines.append(f"name: {entry['qualifiedName']}")
    if entry.get("kind"):
        lines.append(f"kind: {entry['kind']}")
    if entry.get("description"):
        lines.append("description:")
        for desc_line in str(entry["description"]).splitlines() or [""]:
            lines.append(f"  {desc_line}")
    return lines


@app.command("search")
def search_command(
    ctx: typer.Context,
    query: str = typer.Argument(..., help="Поисковый запрос (имя / подстрока)."),
    path: Path | None = typer.Option(
        None,
        "--path",
        help="Каталог проекта (по умолчанию — текущий).",
    ),
    limit: int = typer.Option(20, "--limit", help="Максимум hits."),
    output: OutputOption = None,
) -> None:
    """Поиск по индексу синтакс-помощника текущей platform.version."""
    fmt = resolve_output(ctx, output)
    result = search_docs(path, query, limit=limit)
    _emit(result.to_payload(), fmt, text_lines=_search_text(result))
    raise typer.Exit(code=_exit_code(result))


@app.command("get")
def get_command(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Имя или Owner.Member (например Массив.Добавить)."),
    path: Path | None = typer.Option(
        None,
        "--path",
        help="Каталог проекта (по умолчанию — текущий).",
    ),
    output: OutputOption = None,
) -> None:
    """Получить карточку элемента синтакс-помощника."""
    fmt = resolve_output(ctx, output)
    result = get_docs(path, name)
    _emit(result.to_payload(), fmt, text_lines=_get_text(result))
    raise typer.Exit(code=_exit_code(result))
