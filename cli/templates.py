"""CLI: 1c-dev templates … (ADR-024 / #91)."""

from __future__ import annotations

import json
from typing import Any

import typer

from cli.output import OutputFormat, OutputOption, resolve_output
from core.exit_codes import PROJECT_ERROR, SUCCESS
from core.templates import (
    CODE_NOT_FOUND,
    TemplatesGetResult,
    TemplatesListResult,
    TemplatesRootsResult,
    templates_get,
    templates_list,
    templates_roots,
)

app = typer.Typer(
    name="templates",
    help="Каталог шаблонов платформы (tmplts / *.mft).",
    add_completion=False,
    no_args_is_help=True,
)


def _emit(payload: dict[str, Any], output: OutputFormat, *, text_lines: list[str]) -> None:
    if output is OutputFormat.json:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for line in text_lines:
            typer.echo(line)


def _roots_text(result: TemplatesRootsResult) -> list[str]:
    lines = [f"status: {result.status}"]
    if not result.roots:
        lines.append("roots: (none)")
    else:
        lines.append("roots:")
        for root in result.roots:
            lines.append(f"  - {root}")
    for diag in result.diagnostics:
        code = diag.get("code", "")
        prefix = f"[{code}] " if code else ""
        lines.append(f"warning: {prefix}{diag.get('message', '')}")
        suggestion = diag.get("suggestion")
        if suggestion:
            lines.append(f"  → {suggestion}")
    return lines


def _list_text(result: TemplatesListResult) -> list[str]:
    lines = [f"status: {result.status}"]
    if not result.templates:
        lines.append("templates: (none)")
    else:
        lines.append("templates:")
        for item in result.templates:
            kind = item.source_kind or "?"
            label = item.catalog or item.name or item.section
            lines.append(
                f"  - {item.id}  {item.vendor or '-'} / {label} "
                f"{item.version or ''} [{kind}]"
            )
    for diag in result.diagnostics:
        code = diag.get("code", "")
        prefix = f"[{code}] " if code else ""
        lines.append(f"warning: {prefix}{diag.get('message', '')}")
        suggestion = diag.get("suggestion")
        if suggestion:
            lines.append(f"  → {suggestion}")
    return lines


def _get_text(result: TemplatesGetResult) -> list[str]:
    if result.status != "ok" or result.template is None:
        lines = ["status: error"]
        for diag in result.diagnostics:
            code = diag.get("code", "")
            prefix = f"[{code}] " if code else ""
            lines.append(f"error: {prefix}{diag.get('message', '')}")
            suggestion = diag.get("suggestion")
            if suggestion:
                lines.append(f"  → {suggestion}")
        return lines
    t = result.template
    lines = [
        "status: ok",
        f"id: {t.id}",
        f"vendor: {t.vendor or ''}",
        f"name: {t.name or ''}",
        f"version: {t.version or ''}",
        f"section: {t.section}",
        f"catalog: {t.catalog or ''}",
        f"source: {t.source or ''}",
        f"sourceKind: {t.source_kind or ''}",
        f"sourcePath: {t.source_path or ''}",
        f"mftPath: {t.mft_path}",
    ]
    return lines


@app.command("roots")
def templates_roots_command(
    ctx: typer.Context,
    output: OutputOption = None,
) -> None:
    """Показать каталоги tmplts (1cestart.cfg + default)."""
    fmt = resolve_output(ctx, output)
    result = templates_roots()
    _emit(result.to_payload(), fmt, text_lines=_roots_text(result))
    raise typer.Exit(code=SUCCESS)


@app.command("list")
def templates_list_command(
    ctx: typer.Context,
    vendor: str | None = typer.Option(
        None,
        "--vendor",
        help="Фильтр по Vendor из *.mft.",
    ),
    name: str | None = typer.Option(
        None,
        "--name",
        help="Фильтр по Name из *.mft.",
    ),
    version: str | None = typer.Option(
        None,
        "--version",
        help="Фильтр по Version из *.mft.",
    ),
    source_kind: str | None = typer.Option(
        None,
        "--source-kind",
        help="Фильтр по типу Source: cf, dt или cfu.",
    ),
    query: str | None = typer.Option(
        None,
        "--query",
        "-q",
        help="Подстрока в vendor/name/catalog/destination.",
    ),
    output: OutputOption = None,
) -> None:
    """Список шаблонов из установленных tmplts (парсинг *.mft)."""
    fmt = resolve_output(ctx, output)
    result = templates_list(
        vendor=vendor,
        name=name,
        version=version,
        source_kind_filter=source_kind,
        query=query,
    )
    _emit(result.to_payload(), fmt, text_lines=_list_text(result))
    raise typer.Exit(code=SUCCESS)


@app.command("get")
def templates_get_command(
    ctx: typer.Context,
    template_id: str = typer.Argument(..., help="Id шаблона из templates.list."),
    output: OutputOption = None,
) -> None:
    """Получить один шаблон по id (vendor/name/version/Source)."""
    fmt = resolve_output(ctx, output)
    result = templates_get(template_id)
    _emit(result.to_payload(), fmt, text_lines=_get_text(result))
    if result.status == "ok":
        raise typer.Exit(code=SUCCESS)
    codes = {d.get("code") for d in result.diagnostics}
    if CODE_NOT_FOUND in codes:
        raise typer.Exit(code=PROJECT_ERROR)
    raise typer.Exit(code=PROJECT_ERROR)
