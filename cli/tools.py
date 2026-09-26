"""CLI: 1c-dev tools sync|clean."""

from __future__ import annotations

import json

import typer

from cli.output import OutputFormat, OutputOption, resolve_output
from core.exit_codes import ENV_UNAVAILABLE, RUNTIME_FAILURE, SUCCESS
from core.toolchain.result import SyncResult, UninstallResult
from core.toolchain.sync import sync_tools
from core.toolchain.uninstall import clean_tools_cache

app = typer.Typer(
    name="tools",
    help="Управление jars toolchain в user cache.",
    add_completion=False,
    no_args_is_help=True,
)


def _text_sync(result: SyncResult) -> list[str]:
    lines = ["Toolchain sync", "", "Components:"]
    for comp in result.components:
        path = f" ({comp.path})" if comp.path else ""
        pin = f" [{comp.pin}]" if comp.pin else ""
        msg = f" — {comp.message}" if comp.message else ""
        lines.append(f"  {comp.id}: {comp.status}{pin}{path}{msg}")
    if result.diagnostics:
        lines.append("")
        lines.append("Diagnostics:")
        for diag in result.diagnostics:
            code = diag.get("code", "")
            prefix = f"[{code}] " if code else ""
            lines.append(f"  {diag.get('severity', 'info')}: {prefix}{diag.get('message', '')}")
            suggestion = diag.get("suggestion")
            if suggestion:
                lines.append(f"    → {suggestion}")
    lines.append("")
    lines.append(f"Status: {result.status}")
    return lines


def _text_clean(result: UninstallResult) -> list[str]:
    lines = [
        "Toolchain clean",
        "",
        f"  cacheRemoved: {result.cache_removed}",
        f"  status: {result.status}",
    ]
    if result.diagnostics:
        lines.append("")
        lines.append("Diagnostics:")
        for diag in result.diagnostics:
            code = diag.get("code", "")
            prefix = f"[{code}] " if code else ""
            lines.append(f"  {diag.get('severity', 'info')}: {prefix}{diag.get('message', '')}")
    return lines


@app.command("sync")
def tools_sync_command(
    ctx: typer.Context,
    output: OutputOption = None,
) -> None:
    """Скачать/собрать jars toolchain в user cache (идемпотентно)."""
    fmt = resolve_output(ctx, output)
    live = fmt is not OutputFormat.json

    def progress(message: str) -> None:
        typer.echo(message, err=True)

    result = sync_tools(
        progress=progress if live else None,
        quiet=not live,
    )
    if fmt is OutputFormat.json:
        typer.echo(json.dumps(result.to_payload(), ensure_ascii=False, indent=2))
    else:
        typer.echo("")
        for line in _text_sync(result):
            typer.echo(line)

    if result.status == "ok":
        raise typer.Exit(code=SUCCESS)
    if result.status == "degraded":
        raise typer.Exit(code=SUCCESS)
    raise typer.Exit(code=ENV_UNAVAILABLE)


@app.command("clean")
def tools_clean_command(
    ctx: typer.Context,
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Подтвердить удаление user cache без запроса.",
    ),
    output: OutputOption = None,
) -> None:
    """Удалить user cache toolchain (jars / docs index). Не снимает CLI-пакет."""
    fmt = resolve_output(ctx, output)
    if not yes:
        msg = "Нужен флаг --yes для удаления cache (~/.cache/1c-dev или %LOCALAPPDATA%\\1c-dev)."
        if fmt is OutputFormat.json:
            typer.echo(
                json.dumps(
                    {
                        "status": "error",
                        "cacheRemoved": False,
                        "packageUninstalled": None,
                        "diagnostics": [
                            {
                                "severity": "error",
                                "code": "1CT045",
                                "message": msg,
                                "source": "toolchain",
                                "suggestion": "1c-dev tools clean --yes",
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            typer.echo(msg)
            typer.echo("  → 1c-dev tools clean --yes")
        raise typer.Exit(code=RUNTIME_FAILURE)

    result = clean_tools_cache()
    if fmt is OutputFormat.json:
        typer.echo(json.dumps(result.to_payload(), ensure_ascii=False, indent=2))
    else:
        for line in _text_clean(result):
            typer.echo(line)
    raise typer.Exit(code=SUCCESS if result.status == "ok" else RUNTIME_FAILURE)
