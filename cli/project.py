"""CLI: 1c-dev project …"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from cli.ide import app as ide_app
from cli.init import init_command
from cli.options import ConfigOption, RuntimeOption
from cli.output import OutputFormat, OutputOption, resolve_output
from core.exit_codes import (
    PROJECT_ERROR,
    RUNTIME_FAILURE,
    SUCCESS,
)
from core.project import (
    CleanResult,
    detect_project,
    list_projects,
    run_clean,
    validate_project,
)
from core.project.constants import (
    CODE_CLEAN_FAILED,
    CODE_CLIENT_RUNNING,
    CODE_CONFIG_AMBIGUOUS,
    CODE_CONFIG_UNKNOWN,
    CODE_CONFIRM_REQUIRED,
    CODE_MANIFEST_MISSING,
    CODE_RUNTIME_AMBIGUOUS,
    CODE_RUNTIME_CONFIG_MISMATCH,
    CODE_RUNTIME_UNKNOWN,
    DEFAULT_LIST_DEPTH,
)
from core.project.result import ProjectResult

app = typer.Typer(
    name="project",
    help="Манифест проекта (.1c-dev/project.yaml).",
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


def _clean_exit_for(result: CleanResult) -> None:
    if result.status == "ok":
        raise typer.Exit(code=SUCCESS)
    codes = {d.get("code") for d in result.diagnostics}
    if CODE_CONFIRM_REQUIRED in codes or CODE_CLIENT_RUNNING in codes or CODE_CLEAN_FAILED in codes:
        raise typer.Exit(code=RUNTIME_FAILURE)
    if codes & {
        CODE_MANIFEST_MISSING,
        CODE_CONFIG_UNKNOWN,
        CODE_RUNTIME_UNKNOWN,
        CODE_CONFIG_AMBIGUOUS,
        CODE_RUNTIME_AMBIGUOUS,
        CODE_RUNTIME_CONFIG_MISMATCH,
    }:
        raise typer.Exit(code=PROJECT_ERROR)
    raise typer.Exit(code=RUNTIME_FAILURE)


def _clean_text(result: CleanResult) -> list[str]:
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
    if result.runtime_dir is not None and result.root is not None:
        try:
            rel = result.runtime_dir.relative_to(result.root).as_posix()
        except ValueError:
            rel = str(result.runtime_dir)
        lines.append(f"runtime: {rel}")
    lines.append(f"sourceCleared: {result.source_cleared}")
    lines.append(f"runtimeCleared: {result.runtime_cleared}")
    if result.removed:
        lines.append("removed: " + ", ".join(result.removed))
    for diag in result.diagnostics:
        if diag.get("severity") == "error":
            continue
        code = diag.get("code", "")
        prefix = f"[{code}] " if code else ""
        sev = diag.get("severity", "info")
        lines.append(f"{sev}: {prefix}{diag.get('message', '')}")
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
    if result.home is not None:
        lines.append(f"home: {result.home}")
    if result.manifest:
        project = result.manifest.get("project")
        if isinstance(project, dict):
            if "name" in project:
                lines.append(f"name: {project['name']}")
            if "type" in project:
                lines.append(f"type: {project['type']}")
    for diag in result.diagnostics:
        if diag.get("severity") == "warning":
            code = diag.get("code", "")
            prefix = f"[{code}] " if code else ""
            lines.append(f"warning: {prefix}{diag.get('message', '')}")
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
    lines = [
        "status: ok",
        f"path: {result.path}",
        f"root: {result.root}",
    ]
    if result.home is not None:
        lines.append(f"home: {result.home}")
    lines.extend(
        [
            f"name: {project.get('name', '')}",
            f"type: {project.get('type', '')}",
            f"platform: {platform.get('version', '')}",
        ]
    )
    if result.runtimes:
        for rt in result.runtimes:
            rid = rt.get("id", "")
            rpath = rt.get("path", "")
            lines.append(f"runtime: {rid} ({rpath})")
    else:
        source = m.get("source", {})
        runtime = m.get("runtime", {})
        lines.append(f"source: {source.get('format', '')} ({source.get('path', '')})")
        lines.append(f"runtime: {runtime.get('type', '')} ({runtime.get('path', '')})")
    return lines


def _list_text(results: list[ProjectResult]) -> list[str]:
    if not results:
        return ["status: ok", "projects: 0"]
    lines = ["status: ok", f"projects: {len(results)}"]
    for item in results:
        lines.append(f"- root: {item.root}")
        lines.append(f"  path: {item.path}")
        if item.home is not None:
            lines.append(f"  home: {item.home}")
        if item.manifest:
            project = item.manifest.get("project")
            if isinstance(project, dict) and "name" in project:
                lines.append(f"  name: {project['name']}")
    return lines


@app.command("clean")
def project_clean(
    ctx: typer.Context,
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Подтвердить удаление source и .1c-dev/runtime/ без запроса.",
    ),
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    output: OutputOption = None,
) -> None:
    """Удалить содержимое source и каталог .1c-dev/runtime/ (манифест / IDE intact)."""
    result = run_clean(
        Path.cwd(),
        yes=yes,
        config_id=config,
        runtime_id=runtime,
    )
    _emit(result.to_payload(), resolve_output(ctx, output), text_lines=_clean_text(result))
    _clean_exit_for(result)


@app.command("detect")
def project_detect(
    ctx: typer.Context,
    output: OutputOption = None,
) -> None:
    """Найти манифест (.1c-dev/project.yaml) от текущего каталога вверх."""
    result = detect_project(Path.cwd())
    payload = result.to_payload(include_manifest=False)
    _emit(payload, resolve_output(ctx, output), text_lines=_detect_text(result))
    _exit_for(result)


@app.command("list")
def project_list(
    ctx: typer.Context,
    path: Path | None = typer.Option(
        None,
        "--path",
        help="Корень сканирования (по умолчанию CWD).",
        exists=False,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
    depth: int = typer.Option(
        DEFAULT_LIST_DEPTH,
        "--depth",
        min=0,
        help="Максимальная глубина сканирования вниз.",
    ),
    output: OutputOption = None,
) -> None:
    """Найти nested проекты (.1c-dev/project.yaml) вниз от path."""
    results = list_projects(path or Path.cwd(), max_depth=depth)
    payload = {
        "status": "ok",
        "projects": [r.to_payload(include_manifest=False) for r in results],
    }
    _emit(payload, resolve_output(ctx, output), text_lines=_list_text(results))
    raise typer.Exit(code=SUCCESS)


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
