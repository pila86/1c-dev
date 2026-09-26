"""CLI: 1c-dev uninstall (cache + uv tool uninstall)."""

from __future__ import annotations

import json

import typer

from cli.output import OutputFormat, OutputOption, resolve_output
from core.exit_codes import RUNTIME_FAILURE, SUCCESS
from core.toolchain.result import UninstallResult
from core.toolchain.uninstall import uninstall_tools


def _text_report(result: UninstallResult) -> list[str]:
    lines = [
        "1c-dev uninstall",
        "",
        f"  cacheRemoved: {result.cache_removed}",
        f"  packageUninstalled: {result.package_uninstalled}",
        f"  status: {result.status}",
    ]
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
    return lines


def uninstall_command(
    ctx: typer.Context,
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Подтвердить удаление cache и снятие uv tool пакета.",
    ),
    keep_package: bool = typer.Option(
        False,
        "--keep-package",
        help="Удалить только cache, не вызывать uv tool uninstall.",
    ),
    output: OutputOption = None,
) -> None:
    """Удалить user cache и снять CLI из PATH (uv tool uninstall 1c-dev)."""
    fmt = resolve_output(ctx, output)
    if not yes:
        msg = (
            "Нужен флаг --yes: будут удалены user cache и (без --keep-package) "
            "пакет `uv tool uninstall 1c-dev`."
        )
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
                                "suggestion": "1c-dev uninstall --yes",
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            typer.echo(msg)
            typer.echo("  → 1c-dev uninstall --yes")
        raise typer.Exit(code=RUNTIME_FAILURE)

    result = uninstall_tools(keep_package=keep_package)
    if fmt is OutputFormat.json:
        typer.echo(json.dumps(result.to_payload(), ensure_ascii=False, indent=2))
    else:
        for line in _text_report(result):
            typer.echo(line)

    if result.status == "ok":
        raise typer.Exit(code=SUCCESS)
    if result.status == "degraded":
        raise typer.Exit(code=SUCCESS)
    raise typer.Exit(code=RUNTIME_FAILURE)
