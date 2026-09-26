"""CLI: 1c-dev ide configure / project ide configure."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any

import typer

from cli.output import OutputFormat, OutputOption, resolve_output
from core.exit_codes import PROJECT_ERROR, SUCCESS
from core.project import configure_ide
from core.project.result import ProjectResult

app = typer.Typer(
    name="ide",
    help="Настройки IDE и агента (MCP, AGENTS.md).",
    add_completion=False,
    no_args_is_help=True,
)


class TargetChoice(str, Enum):
    """IDE target for MCP config wiring."""

    all = "all"
    cursor = "cursor"
    kilocode = "kilocode"
    none = "none"


def _emit(payload: dict[str, Any], output: OutputFormat, *, text_lines: list[str]) -> None:
    if output is OutputFormat.json:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for line in text_lines:
            typer.echo(line)


def _configure_text(result: ProjectResult) -> list[str]:
    if result.status != "ok":
        lines = ["status: error"]
        for diag in result.diagnostics:
            code = diag.get("code", "")
            prefix = f"[{code}] " if code else ""
            severity = diag.get("severity", "error")
            lines.append(f"{severity}: {prefix}{diag.get('message', '')}")
            suggestion = diag.get("suggestion")
            if suggestion:
                lines.append(f"  → {suggestion}")
        return lines

    lines = [
        "status: ok",
        f"path: {result.path}",
        f"root: {result.root}",
    ]
    if result.created:
        lines.append("created:")
        for item in result.created:
            lines.append(f"  - {item}")
    if result.updated:
        lines.append("updated:")
        for item in result.updated:
            lines.append(f"  - {item}")
    if result.skipped:
        lines.append("skipped:")
        for item in result.skipped:
            lines.append(f"  - {item}")
    for diag in result.diagnostics:
        if diag.get("severity") == "warning":
            code = diag.get("code", "")
            prefix = f"[{code}] " if code else ""
            lines.append(f"warning: {prefix}{diag.get('message', '')}")
    return lines


@app.command("configure")
def configure_command(
    ctx: typer.Context,
    target: TargetChoice = typer.Option(
        TargetChoice.all,
        "--target",
        help="IDE MCP: all (default), cursor, kilocode, или none (без MCP).",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Перезаписать AGENTS.md, .gitignore и IDE MCP шаблоном.",
    ),
    output: OutputOption = None,
) -> None:
    """Настроить IDE MCP, AGENTS.md и .gitignore для существующего проекта."""
    result = configure_ide(
        Path.cwd(),
        target=target.value,
        force=force,
    )
    payload = result.to_payload(include_manifest=False)
    _emit(payload, resolve_output(ctx, output), text_lines=_configure_text(result))
    code = SUCCESS if result.status == "ok" else PROJECT_ERROR
    raise typer.Exit(code=code)
