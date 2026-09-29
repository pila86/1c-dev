"""CLI: 1c-dev configuration … (ADR-027 / #100)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from cli.output import OutputFormat, OutputOption, resolve_output
from core.configuration import (
    ConfigurationListResult,
    add_configuration,
    get_configuration,
    list_configurations,
    remove_configuration,
    set_default_configuration,
)
from core.exit_codes import PROJECT_ERROR, SUCCESS
from core.project.result import ProjectResult

app = typer.Typer(
    name="configuration",
    help="Lifecycle конфигураций в scope (add / list / get / remove / set-default).",
    add_completion=False,
    no_args_is_help=True,
)


def _emit(payload: dict[str, Any], output: OutputFormat, *, text_lines: list[str]) -> None:
    if output is OutputFormat.json:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for line in text_lines:
            typer.echo(line)


def _project_text(result: ProjectResult) -> list[str]:
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
    if result.root is not None:
        lines.append(f"root: {result.root}")
    if result.created:
        lines.append("created:")
        for item in result.created:
            lines.append(f"  - {item}")
    if result.updated:
        lines.append("updated:")
        for item in result.updated:
            lines.append(f"  - {item}")
    if result.manifest and "configuration" in result.manifest:
        conf = result.manifest["configuration"]
        if isinstance(conf, dict):
            lines.append(f"id: {conf.get('id')}")
            source = conf.get("source")
            if isinstance(source, dict):
                lines.append(f"path: {source.get('path')}")
            lines.append(f"default: {conf.get('default') is True}")
    return lines


def _list_text(result: ConfigurationListResult) -> list[str]:
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
    if not result.configurations:
        lines.append("configurations: (none)")
    else:
        lines.append("configurations:")
        for conf in result.configurations:
            default = " default" if conf.get("default") else ""
            lines.append(f"  - {conf.get('id')} ({conf.get('path')}){default}")
    return lines


@app.command("add")
def configuration_add_command(
    ctx: typer.Context,
    config_id: str | None = typer.Option(
        None,
        "--id",
        help="Id configuration в манифесте (по умолчанию = --name).",
    ),
    name: str | None = typer.Option(
        None,
        "--name",
        help="Имя конфигурации в XML (по умолчанию = --id).",
    ),
    source_path: str | None = typer.Option(
        None,
        "--path",
        help="Каталог исходников относительно scope (default: src/<id>).",
    ),
    set_default: bool = typer.Option(
        False,
        "--set-default",
        help="Сделать эту configuration default (иначе — только если первая).",
    ),
    with_runtime: bool = typer.Option(
        True,
        "--with-runtime/--no-runtime",
        help="Создать связанный runtime (.1c-dev/runtime/<id>).",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Перезаписать исходники, если каталог уже есть.",
    ),
    output: OutputOption = None,
) -> None:
    """Добавить configuration: scaffold XML + манифест + runtime."""
    result = add_configuration(
        Path.cwd(),
        config_id=config_id,
        name=name,
        source_path=source_path,
        set_default=True if set_default else None,
        with_runtime=with_runtime,
        force=force,
    )
    payload = result.to_payload(include_manifest=False)
    _emit(payload, resolve_output(ctx, output), text_lines=_project_text(result))
    raise typer.Exit(code=SUCCESS if result.status == "ok" else PROJECT_ERROR)


@app.command("list")
def configuration_list_command(
    ctx: typer.Context,
    output: OutputOption = None,
) -> None:
    """Краткий список configurations в scope."""
    result = list_configurations(Path.cwd())
    _emit(
        result.to_payload(),
        resolve_output(ctx, output),
        text_lines=_list_text(result),
    )
    raise typer.Exit(code=SUCCESS if result.status == "ok" else PROJECT_ERROR)


@app.command("get")
def configuration_get_command(
    ctx: typer.Context,
    config_id: str = typer.Option(..., "--id", help="Id configuration."),
    output: OutputOption = None,
) -> None:
    """Детали одной configuration и связанные runtimes."""
    result = get_configuration(Path.cwd(), config_id=config_id)
    payload = result.to_payload(include_manifest=True)
    _emit(payload, resolve_output(ctx, output), text_lines=_project_text(result))
    raise typer.Exit(code=SUCCESS if result.status == "ok" else PROJECT_ERROR)


@app.command("remove")
def configuration_remove_command(
    ctx: typer.Context,
    config_id: str = typer.Option(..., "--id", help="Id configuration."),
    yes: bool = typer.Option(
        False,
        "--yes",
        help="Подтвердить удаление из манифеста.",
    ),
    wipe_source: bool = typer.Option(
        False,
        "--wipe-source",
        help="Удалить каталог исходников.",
    ),
    wipe_runtime: bool = typer.Option(
        False,
        "--wipe-runtime",
        help="Удалить связанные runtime-каталоги.",
    ),
    output: OutputOption = None,
) -> None:
    """Удалить configuration из манифеста (требует --yes)."""
    result = remove_configuration(
        Path.cwd(),
        config_id=config_id,
        yes=yes,
        wipe_source=wipe_source,
        wipe_runtime=wipe_runtime,
    )
    payload = result.to_payload(include_manifest=False)
    _emit(payload, resolve_output(ctx, output), text_lines=_project_text(result))
    raise typer.Exit(code=SUCCESS if result.status == "ok" else PROJECT_ERROR)


@app.command("set-default")
def configuration_set_default_command(
    ctx: typer.Context,
    config_id: str = typer.Option(..., "--id", help="Id configuration."),
    output: OutputOption = None,
) -> None:
    """Сделать configuration default в scope."""
    result = set_default_configuration(Path.cwd(), config_id=config_id)
    payload = result.to_payload(include_manifest=False)
    _emit(payload, resolve_output(ctx, output), text_lines=_project_text(result))
    raise typer.Exit(code=SUCCESS if result.status == "ok" else PROJECT_ERROR)
