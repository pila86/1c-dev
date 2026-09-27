"""CLI: 1c-dev init / project init."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any

import typer

from cli.output import OutputFormat, OutputOption, resolve_output
from core.exit_codes import PROJECT_ERROR, SUCCESS
from core.project import init_project
from core.project.result import ProjectResult


class IdeTargetChoice(str, Enum):
    """IDE target for MCP config wiring on init."""

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


def _init_text(result: ProjectResult) -> list[str]:
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

    lines = [
        "status: ok",
        f"path: {result.path}",
        f"root: {result.root}",
    ]
    if result.manifest:
        project = result.manifest.get("project", {})
        if isinstance(project, dict):
            if "name" in project:
                lines.append(f"name: {project['name']}")
            if "type" in project:
                lines.append(f"type: {project['type']}")
    if result.created:
        lines.append("created:")
        for item in result.created:
            lines.append(f"  - {item}")
    for diag in result.diagnostics:
        if diag.get("severity") == "warning":
            code = diag.get("code", "")
            prefix = f"[{code}] " if code else ""
            lines.append(f"warning: {prefix}{diag.get('message', '')}")
    return lines


def init_command(
    ctx: typer.Context,
    project_type: str = typer.Option(
        ...,
        "--type",
        help="Тип проекта: configuration (M1).",
    ),
    name: str | None = typer.Option(
        None,
        "--name",
        help="Имя конфигурации (по умолчанию — имя текущего каталога).",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Перезаписать существующий манифест и шаблоны.",
    ),
    ide_target: IdeTargetChoice = typer.Option(
        IdeTargetChoice.all,
        "--ide-target",
        help="IDE MCP: all (default), cursor, kilocode, или none (без MCP).",
    ),
    output: OutputOption = None,
) -> None:
    """Создать пустой проект конфигурации (bootstrap)."""
    result = init_project(
        Path.cwd(),
        project_type=project_type,
        name=name,
        force=force,
        ide_target=ide_target.value,
    )
    payload = result.to_payload(include_manifest=False)
    _emit(payload, resolve_output(ctx, output), text_lines=_init_text(result))
    code = SUCCESS if result.status == "ok" else PROJECT_ERROR
    raise typer.Exit(code=code)
