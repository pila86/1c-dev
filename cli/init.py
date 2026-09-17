"""CLI: 1c-dev init / project init."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from cli.output import OutputFormat
from core.exit_codes import PROJECT_ERROR, SUCCESS
from core.project import init_project
from core.project.result import ProjectResult


def _output_format(ctx: typer.Context) -> OutputFormat:
    raw = ctx.obj.get("output", OutputFormat.text) if ctx.obj else OutputFormat.text
    if isinstance(raw, OutputFormat):
        return raw
    return OutputFormat(str(raw))


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
) -> None:
    """Создать пустой проект конфигурации (bootstrap)."""
    result = init_project(
        Path.cwd(),
        project_type=project_type,
        name=name,
        force=force,
    )
    payload = result.to_payload(include_manifest=False)
    _emit(payload, _output_format(ctx), text_lines=_init_text(result))
    code = SUCCESS if result.status == "ok" else PROJECT_ERROR
    raise typer.Exit(code=code)
