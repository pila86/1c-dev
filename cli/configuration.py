"""CLI: 1c-dev configuration … (ADR-027 / ADR-028 / #100)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from adapters.platform_ibcmd.constants import CODE_IBCMD_FAILED
from cli.output import OutputFormat, OutputOption, resolve_output
from core.configuration import (
    ConfigurationListResult,
    add_configuration,
    get_configuration,
    list_configurations,
    remove_configuration,
    set_default_configuration,
)
from core.exit_codes import BUILD_FAILURE, ENV_UNAVAILABLE, PROJECT_ERROR, SUCCESS
from core.import_cf import ImportResult, run_import
from core.import_cf.constants import (
    CODE_CF_MISSING,
    CODE_DIRTY_SOURCE,
    CODE_EXPORT_MISSING,
    CODE_IBCMD_MISSING,
    CODE_PROJECT,
)
from core.project.result import ProjectResult

app = typer.Typer(
    name="configuration",
    help="Lifecycle конфигураций в scope (add / import / list / get / remove / set-default).",
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


@app.command("import")
def configuration_import_command(
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
    config_id: str | None = typer.Option(
        None,
        "--id",
        help="Id configuration (по умолчанию: default conf или main при создании).",
    ),
    source_path: str | None = typer.Option(
        None,
        "--path",
        help="Каталог исходников при создании conf (default: src/<id>).",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Перезаписать существующий XML source (Configuration.xml).",
    ),
    break_support: bool = typer.Option(
        False,
        "--break-support",
        help=(
            "После export удалить артефакты поддержки поставщика "
            "(ParentConfigurations*) из source.path. "
            "Теряется возможность штатного обновления от поставщика."
        ),
    ),
    with_runtime: bool = typer.Option(
        True,
        "--with-runtime/--no-runtime",
        help="При создании conf — связанный runtime (.1c-dev/runtime/<id>).",
    ),
    output: OutputOption = None,
) -> None:
    """Импортировать .cf в XML source configuration (CF → IB → export)."""
    result = run_import(
        Path.cwd(),
        from_path=from_path,
        force=force,
        break_support=break_support,
        config_id=config_id,
        source_path=source_path,
        with_runtime=with_runtime,
    )
    _emit(result.to_payload(), resolve_output(ctx, output), text_lines=_import_text(result))
    _import_exit_for(result)


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
