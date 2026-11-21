"""CLI: 1c-dev tools list|info|install|remove (+ alias sync|clean → toolchain)."""

from __future__ import annotations

import json

import typer

from cli.output import OutputFormat, OutputOption, resolve_output
from cli.toolchain import toolchain_clean_command, toolchain_sync_command
from core.exit_codes import ENV_UNAVAILABLE, RUNTIME_FAILURE, SUCCESS
from core.tools.catalog import list_catalog
from core.tools.install import (
    install_tool,
    list_installed,
    remove_tool,
    tool_info,
)

app = typer.Typer(
    name="tools",
    help=(
        "Внешние инструменты (catalog / install). "
        "Alias: sync|clean → toolchain (deprecated path)."
    ),
    add_completion=False,
    no_args_is_help=True,
)


def _emit_diags_text(diagnostics: list[dict[str, object]] | list[object]) -> None:
    if not diagnostics:
        return
    typer.echo("Diagnostics:")
    for diag in diagnostics:
        if not isinstance(diag, dict):
            continue
        code = diag.get("code", "")
        prefix = f"[{code}] " if code else ""
        typer.echo(f"  {diag.get('severity', 'info')}: {prefix}{diag.get('message', '')}")
        suggestion = diag.get("suggestion")
        if suggestion:
            typer.echo(f"    → {suggestion}")


@app.command("list")
def tools_list_command(
    ctx: typer.Context,
    output: OutputOption = None,
) -> None:
    """Список tools из catalog и установленных в share."""
    fmt = resolve_output(ctx, output)
    catalog_ids = list_catalog()
    installed = set(list_installed())
    items = []
    for tool_id in catalog_ids:
        info = tool_info(tool_id)
        items.append(info.to_payload())
    for tool_id in sorted(installed - set(catalog_ids)):
        items.append(
            {
                "id": tool_id,
                "name": tool_id,
                "version": None,
                "mcpName": tool_id,
                "installed": True,
                "path": None,
                "lifecycle": "unknown",
                "mcpUrl": None,
            }
        )
    payload = {"tools": items, "status": "ok"}
    if fmt is OutputFormat.json:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        typer.echo("External tools")
        typer.echo("")
        for item in items:
            mark = "installed" if item.get("installed") else "catalog"
            typer.echo(f"  {item['id']}: {mark} ({item.get('name')})")
    raise typer.Exit(code=SUCCESS)


@app.command("info")
def tools_info_command(
    ctx: typer.Context,
    tool_id: str = typer.Argument(..., help="Id tool из catalog (например v8std)."),
    output: OutputOption = None,
) -> None:
    """Информация о tool (catalog + install status)."""
    fmt = resolve_output(ctx, output)
    try:
        info = tool_info(tool_id)
    except FileNotFoundError:
        message = f"tool «{tool_id}» не найден в catalog"
        payload: dict[str, object] = {
            "status": "error",
            "diagnostics": [
                {
                    "severity": "error",
                    "code": "1CX001",
                    "message": message,
                    "source": "tools",
                }
            ],
        }
        if fmt is OutputFormat.json:
            typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            typer.echo(message)
        raise typer.Exit(code=RUNTIME_FAILURE) from None

    payload = {"status": "ok", **info.to_payload()}
    if fmt is OutputFormat.json:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        typer.echo(f"{info.id} — {info.name}")
        typer.echo(f"  version: {info.version}")
        typer.echo(f"  mcpName: {info.mcp_name}")
        typer.echo(f"  installed: {info.installed}")
        if info.path:
            typer.echo(f"  path: {info.path}")
        if info.mcp_url:
            typer.echo(f"  mcpUrl: {info.mcp_url}")
    raise typer.Exit(code=SUCCESS)


@app.command("install")
def tools_install_command(
    ctx: typer.Context,
    tool_id: str = typer.Argument(..., help="Id tool из catalog."),
    no_pull: bool = typer.Option(
        False,
        "--no-pull",
        help="Только материализовать recipe, без docker compose pull.",
    ),
    output: OutputOption = None,
) -> None:
    """Установить recipe в share (+ pull images). Не запускает сервис."""
    fmt = resolve_output(ctx, output)
    live = fmt is not OutputFormat.json

    def progress(message: str) -> None:
        typer.echo(message, err=True)

    result = install_tool(
        tool_id,
        pull=not no_pull,
        progress=progress if live else None,
    )
    if fmt is OutputFormat.json:
        typer.echo(json.dumps(result.to_payload(), ensure_ascii=False, indent=2))
    else:
        typer.echo(f"tools install {tool_id}: {result.status}")
        if result.path:
            typer.echo(f"  path: {result.path}")
        typer.echo(f"  pulled: {result.pulled}")
        _emit_diags_text(result.diagnostics)  # type: ignore[arg-type]
    if result.status == "ok":
        raise typer.Exit(code=SUCCESS)
    # Docker missing / pull fail → ENV_UNAVAILABLE; recipe errors → RUNTIME
    codes = {d.get("code") for d in result.diagnostics}
    if "1CX003" in codes:
        raise typer.Exit(code=ENV_UNAVAILABLE)
    raise typer.Exit(code=RUNTIME_FAILURE)


@app.command("remove")
def tools_remove_command(
    ctx: typer.Context,
    tool_id: str = typer.Argument(..., help="Id установленного tool."),
    output: OutputOption = None,
) -> None:
    """Удалить recipe из share (stack не останавливает автоматически)."""
    fmt = resolve_output(ctx, output)
    result = remove_tool(tool_id)
    if fmt is OutputFormat.json:
        typer.echo(json.dumps(result.to_payload(), ensure_ascii=False, indent=2))
    else:
        typer.echo(f"tools remove {tool_id}: {result.status}")
        _emit_diags_text(result.diagnostics)  # type: ignore[arg-type]
    raise typer.Exit(code=SUCCESS if result.status == "ok" else RUNTIME_FAILURE)


# --- Alias: tools sync|clean → toolchain (ADR-033, ≥1 minor) ---


@app.command("sync")
def tools_sync_alias(
    ctx: typer.Context,
    output: OutputOption = None,
) -> None:
    """Alias → `toolchain sync` (переходный период)."""
    if resolve_output(ctx, output) is not OutputFormat.json:
        typer.echo(
            "note: `tools sync` — alias; канон: `1c-dev toolchain sync`",
            err=True,
        )
    toolchain_sync_command(ctx, output=output)


@app.command("clean")
def tools_clean_alias(
    ctx: typer.Context,
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Подтвердить удаление user cache без запроса.",
    ),
    output: OutputOption = None,
) -> None:
    """Alias → `toolchain clean` (переходный период)."""
    if resolve_output(ctx, output) is not OutputFormat.json:
        typer.echo(
            "note: `tools clean` — alias; канон: `1c-dev toolchain clean`",
            err=True,
        )
    toolchain_clean_command(ctx, yes=yes, output=output)
