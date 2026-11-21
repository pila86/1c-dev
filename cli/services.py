"""CLI: 1c-dev services up|down|status|logs (ADR-033)."""

from __future__ import annotations

import json

import typer

from cli.output import OutputFormat, OutputOption, resolve_output
from core.exit_codes import ENV_UNAVAILABLE, RUNTIME_FAILURE, SUCCESS
from core.services.manager import (
    service_down,
    service_logs,
    service_restart,
    service_status,
    service_up,
)

app = typer.Typer(
    name="services",
    help="Lifecycle managed external tools (docker compose).",
    add_completion=False,
    no_args_is_help=True,
)


def _emit_text(result: object) -> None:
    payload = result.to_payload()  # type: ignore[attr-defined]
    typer.echo(f"services {payload['action']} {payload['toolId']}: {payload['status']}")
    if payload.get("healthUrl"):
        typer.echo(f"  healthUrl: {payload['healthUrl']}")
    if payload.get("mcpUrl"):
        typer.echo(f"  mcpUrl: {payload['mcpUrl']}")
    if payload.get("healthy") is not None:
        typer.echo(f"  healthy: {payload['healthy']}")
    if payload.get("logs"):
        typer.echo("")
        typer.echo(payload["logs"])
    diags = payload.get("diagnostics") or []
    if diags:
        typer.echo("Diagnostics:")
        for diag in diags:
            code = diag.get("code", "")
            prefix = f"[{code}] " if code else ""
            typer.echo(f"  {diag.get('severity', 'info')}: {prefix}{diag.get('message', '')}")
            if diag.get("suggestion"):
                typer.echo(f"    → {diag['suggestion']}")


def _exit_for(result: object) -> None:
    payload = result.to_payload()  # type: ignore[attr-defined]
    status = payload["status"]
    if status == "ok":
        raise typer.Exit(code=SUCCESS)
    codes = {d.get("code") for d in (payload.get("diagnostics") or [])}
    if "1CX003" in codes:
        raise typer.Exit(code=ENV_UNAVAILABLE)
    if status == "degraded":
        raise typer.Exit(code=SUCCESS)
    raise typer.Exit(code=RUNTIME_FAILURE)


@app.command("up")
def services_up_command(
    ctx: typer.Context,
    tool_id: str = typer.Argument(..., help="Id установленного tool."),
    output: OutputOption = None,
) -> None:
    """Поднять managed stack (идемпотентно)."""
    fmt = resolve_output(ctx, output)
    live = fmt is not OutputFormat.json

    def progress(message: str) -> None:
        typer.echo(message, err=True)

    result = service_up(tool_id, progress=progress if live else None)
    if fmt is OutputFormat.json:
        typer.echo(json.dumps(result.to_payload(), ensure_ascii=False, indent=2))
    else:
        _emit_text(result)
    _exit_for(result)


@app.command("down")
def services_down_command(
    ctx: typer.Context,
    tool_id: str = typer.Argument(..., help="Id установленного tool."),
    output: OutputOption = None,
) -> None:
    """Остановить managed stack."""
    fmt = resolve_output(ctx, output)
    live = fmt is not OutputFormat.json

    def progress(message: str) -> None:
        typer.echo(message, err=True)

    result = service_down(tool_id, progress=progress if live else None)
    if fmt is OutputFormat.json:
        typer.echo(json.dumps(result.to_payload(), ensure_ascii=False, indent=2))
    else:
        _emit_text(result)
    _exit_for(result)


@app.command("restart")
def services_restart_command(
    ctx: typer.Context,
    tool_id: str = typer.Argument(..., help="Id установленного tool."),
    output: OutputOption = None,
) -> None:
    """Перезапустить managed stack (down + up)."""
    fmt = resolve_output(ctx, output)
    live = fmt is not OutputFormat.json

    def progress(message: str) -> None:
        typer.echo(message, err=True)

    result = service_restart(tool_id, progress=progress if live else None)
    if fmt is OutputFormat.json:
        typer.echo(json.dumps(result.to_payload(), ensure_ascii=False, indent=2))
    else:
        _emit_text(result)
    _exit_for(result)


@app.command("status")
def services_status_command(
    ctx: typer.Context,
    tool_id: str = typer.Argument(..., help="Id установленного tool."),
    output: OutputOption = None,
) -> None:
    """Статус / health managed stack."""
    fmt = resolve_output(ctx, output)
    result = service_status(tool_id)
    if fmt is OutputFormat.json:
        typer.echo(json.dumps(result.to_payload(), ensure_ascii=False, indent=2))
    else:
        _emit_text(result)
    _exit_for(result)


@app.command("logs")
def services_logs_command(
    ctx: typer.Context,
    tool_id: str = typer.Argument(..., help="Id установленного tool."),
    tail: int = typer.Option(100, "--tail", help="Число строк логов."),
    output: OutputOption = None,
) -> None:
    """Логи docker compose stack."""
    fmt = resolve_output(ctx, output)
    result = service_logs(tool_id, tail=tail)
    if fmt is OutputFormat.json:
        typer.echo(json.dumps(result.to_payload(), ensure_ascii=False, indent=2))
    else:
        _emit_text(result)
    _exit_for(result)
