"""CLI: 1c-dev metadata …"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from cli.output import OutputFormat, OutputOption, resolve_output
from core.exit_codes import ENV_UNAVAILABLE, PROJECT_ERROR, SUCCESS
from core.metadata import (
    IrError,
    MetadataResult,
    catalog_from_json,
    catalog_from_parts,
    create_metadata,
    load_json_input,
)

app = typer.Typer(
    name="metadata",
    help="Семантические операции с метаданными (IR).",
    add_completion=False,
    no_args_is_help=True,
)


def _emit(payload: dict[str, Any], output: OutputFormat, *, text_lines: list[str]) -> None:
    if output is OutputFormat.json:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for line in text_lines:
            typer.echo(line)


def _create_text(result: MetadataResult) -> list[str]:
    if result.status != "ok":
        lines = ["status: error"]
        for diag in result.diagnostics:
            code = diag.get("code", "")
            prefix = f"[{code}] " if code else ""
            lines.append(f"error: {prefix}{diag.get('message', '')}")
            suggestion = diag.get("suggestion")
            if suggestion:
                lines.append(f"  → {suggestion}")
        return lines
    lines = ["status: ok"]
    if result.object:
        lines.append(f"object: {result.object}")
    if result.root:
        lines.append(f"root: {result.root}")
    if result.created:
        lines.append("created:")
        for item in result.created:
            lines.append(f"  - {item}")
    return lines


def _exit_for(result: MetadataResult) -> None:
    if result.status == "ok":
        raise typer.Exit(code=SUCCESS)
    codes = {d.get("code") for d in result.diagnostics}
    if "1CM006" in codes:
        raise typer.Exit(code=ENV_UNAVAILABLE)
    raise typer.Exit(code=PROJECT_ERROR)


@app.command("create")
def create_command(
    ctx: typer.Context,
    qualified_name: str = typer.Argument(
        ...,
        help="Qualified name, например Catalog.Products.",
    ),
    synonym: str | None = typer.Option(
        None,
        "--synonym",
        help="Синоним объекта.",
    ),
    attr: list[str] | None = typer.Option(
        None,
        "--attr",
        help="Реквизит Name:Type[:LengthOrPrecision][:Synonym], можно повторять.",
    ),
    from_json: str | None = typer.Option(
        None,
        "--from-json",
        help="Путь к JSON IR или '-' для stdin.",
    ),
    output: OutputOption = None,
) -> None:
    """Создать объект метаданных (M1: Catalog) через xml-gen."""
    fmt = resolve_output(ctx, output)
    try:
        if from_json is not None:
            data = load_json_input(from_json)
            if synonym and "synonym" not in data:
                data["synonym"] = synonym
            if attr:
                # merge CLI attrs into JSON list
                existing = list(data.get("attributes") or [])
                existing.extend(attr)
                data["attributes"] = existing
            catalog = catalog_from_json(data, qualified_name=qualified_name)
            if synonym and not catalog.synonym:
                catalog.synonym = synonym
        else:
            catalog = catalog_from_parts(
                qualified_name=qualified_name,
                synonym=synonym,
                attr_specs=list(attr or []),
            )
    except IrError as exc:
        result = MetadataResult(
            status="error",
            diagnostics=[
                {
                    "severity": "error",
                    "code": exc.code,
                    "message": exc.message,
                    "source": "metadata",
                }
            ],
        )
        _emit(result.to_payload(), fmt, text_lines=_create_text(result))
        _exit_for(result)
        return
    except (OSError, json.JSONDecodeError) as exc:
        result = MetadataResult(
            status="error",
            diagnostics=[
                {
                    "severity": "error",
                    "code": "1CM004",
                    "message": f"Не удалось прочитать JSON: {exc}",
                    "source": "metadata",
                }
            ],
        )
        _emit(result.to_payload(), fmt, text_lines=_create_text(result))
        _exit_for(result)
        return

    result = create_metadata(Path.cwd(), catalog)
    _emit(result.to_payload(), fmt, text_lines=_create_text(result))
    _exit_for(result)
