"""CLI: 1c-dev project …"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from adapters.platform_ibcmd.constants import CODE_IBCMD_FAILED
from cli.ide import app as ide_app
from cli.init import init_command
from cli.output import OutputFormat, OutputOption, resolve_output
from core.exit_codes import BUILD_FAILURE, ENV_UNAVAILABLE, PROJECT_ERROR, SUCCESS
from core.import_cf import ImportResult, run_import
from core.import_cf.constants import (
    CODE_CF_MISSING,
    CODE_DIRTY_SOURCE,
    CODE_EXPORT_MISSING,
    CODE_IBCMD_MISSING,
    CODE_PROJECT,
)
from core.project import detect_project, validate_project
from core.project.result import ProjectResult

app = typer.Typer(
    name="project",
    help="Манифест проекта (1c.project.yaml).",
    add_completion=False,
    no_args_is_help=True,
)

app.command("init")(init_command)
app.add_typer(ide_app, name="ide")


def _emit(payload: dict[str, Any], output: OutputFormat, *, text_lines: list[str]) -> None:
    if output is OutputFormat.json:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for line in text_lines:
            typer.echo(line)


def _exit_for(result: ProjectResult) -> None:
    code = SUCCESS if result.status == "ok" else PROJECT_ERROR
    raise typer.Exit(code=code)


def _import_exit_for(result: ImportResult) -> None:
    if result.status == "ok":
        raise typer.Exit(code=SUCCESS)
    codes = {d.get("code") for d in result.diagnostics}
    if CODE_IBCMD_MISSING in codes:
        raise typer.Exit(code=ENV_UNAVAILABLE)
    if codes & {
        CODE_CF_MISSING,
        CODE_PROJECT,
        CODE_DIRTY_SOURCE,
    }:
        raise typer.Exit(code=PROJECT_ERROR)
    if codes & {CODE_IBCMD_FAILED, CODE_EXPORT_MISSING}:
        raise typer.Exit(code=BUILD_FAILURE)
    raise typer.Exit(code=BUILD_FAILURE)


def _import_text(result: ImportResult) -> list[str]:
    if result.status != "ok":
        lines = ["status: failed"]
        for diag in result.diagnostics:
            code = diag.get("code", "")
            prefix = f"[{code}] " if code else ""
            lines.append(f"error: {prefix}{diag.get('message', '')}")
            suggestion = diag.get("suggestion")
            if suggestion:
                lines.append(f"  → {suggestion}")
        return lines

    lines = ["status: ok"]
    if result.duration is not None:
        lines.append(f"duration: {result.duration:.3f}s")
    if result.source_path is not None and result.root is not None:
        try:
            rel = result.source_path.relative_to(result.root).as_posix()
        except ValueError:
            rel = str(result.source_path)
        lines.append(f"source: {rel}")
    if result.runtime_path is not None and result.root is not None:
        try:
            rel = result.runtime_path.relative_to(result.root).as_posix()
        except ValueError:
            rel = str(result.runtime_path)
        lines.append(f"runtime: {rel}")
    if result.from_path is not None:
        lines.append(f"from: {result.from_path}")
    if result.steps:
        lines.append("steps: " + ", ".join(result.steps))
    if result.created:
        lines.append("created: " + ", ".join(result.created))
    return lines


def _detect_text(result: ProjectResult) -> list[str]:
    if result.status != "ok" or result.path is None:
        lines = ["status: error"]
        for diag in result.diagnostics:
            lines.append(f"error: {diag.get('message', '')}")
        return lines
    lines = [
        "status: ok",
        f"path: {result.path}",
        f"root: {result.root}",
    ]
    if result.manifest:
        project = result.manifest.get("project")
        if isinstance(project, dict):
            if "name" in project:
                lines.append(f"name: {project['name']}")
            if "type" in project:
                lines.append(f"type: {project['type']}")
    return lines


def _validate_text(result: ProjectResult) -> list[str]:
    if result.status == "ok":
        return [
            "status: ok",
            f"path: {result.path}",
            "manifest: valid",
        ]
    lines = ["status: error"]
    for diag in result.diagnostics:
        code = diag.get("code", "")
        prefix = f"[{code}] " if code else ""
        lines.append(f"error: {prefix}{diag.get('message', '')}")
    return lines


def _info_text(result: ProjectResult) -> list[str]:
    if result.status != "ok" or result.manifest is None:
        return _validate_text(result)
    m = result.manifest
    project = m.get("project", {})
    platform = m.get("platform", {})
    source = m.get("source", {})
    runtime = m.get("runtime", {})
    return [
        "status: ok",
        f"path: {result.path}",
        f"name: {project.get('name', '')}",
        f"type: {project.get('type', '')}",
        f"platform: {platform.get('version', '')}",
        f"source: {source.get('format', '')} ({source.get('path', '')})",
        f"runtime: {runtime.get('type', '')} ({runtime.get('path', '')})",
    ]


@app.command("import")
def project_import(
    ctx: typer.Context,
    from_path: Path = typer.Option(
        ...,
        "--from",
        help="Путь к файлу конфигурации (.cf).",
        exists=False,
        dir_okay=False,
        file_okay=True,
        resolve_path=False,
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Перезаписать существующий XML source (Configuration.xml).",
    ),
    output: OutputOption = None,
) -> None:
    """Импортировать .cf в XML source проекта (CF → IB → export)."""
    result = run_import(Path.cwd(), from_path=from_path, force=force)
    _emit(result.to_payload(), resolve_output(ctx, output), text_lines=_import_text(result))
    _import_exit_for(result)


@app.command("detect")
def project_detect(
    ctx: typer.Context,
    output: OutputOption = None,
) -> None:
    """Найти 1c.project.yaml от текущего каталога вверх."""
    result = detect_project(Path.cwd())
    payload = result.to_payload(include_manifest=False)
    _emit(payload, resolve_output(ctx, output), text_lines=_detect_text(result))
    _exit_for(result)


@app.command("validate")
def project_validate(
    ctx: typer.Context,
    output: OutputOption = None,
) -> None:
    """Проверить манифест по JSON Schema."""
    result = validate_project(Path.cwd())
    payload = result.to_payload(include_manifest=False)
    if result.status == "ok":
        payload["valid"] = True
    _emit(payload, resolve_output(ctx, output), text_lines=_validate_text(result))
    _exit_for(result)


@app.command("info")
def project_info(
    ctx: typer.Context,
    output: OutputOption = None,
) -> None:
    """Показать содержимое валидного манифеста."""
    result = validate_project(Path.cwd())
    payload = result.to_payload(include_manifest=True)
    _emit(payload, resolve_output(ctx, output), text_lines=_info_text(result))
    _exit_for(result)
