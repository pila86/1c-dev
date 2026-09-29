"""CLI: 1c-dev publish … (ADR-025)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from cli.output import OutputFormat, OutputOption, resolve_output
from core.exit_codes import ENV_UNAVAILABLE, PROJECT_ERROR, RUNTIME_FAILURE, SUCCESS
from core.publish import (
    CODE_BACKEND_UNSUPPORTED,
    CODE_IB_MISSING,
    CODE_IBCMD_MISSING,
    CODE_IBSRV_FAILED,
    CODE_IBSRV_MISSING,
    CODE_PROFILE_UNKNOWN,
    CODE_PROJECT,
    PublishResult,
    run_down,
    run_status,
    run_up,
    run_url,
)

app = typer.Typer(
    name="publish",
    help="Публикация file IB через ibsrv (HTTP).",
    add_completion=False,
    no_args_is_help=True,
)

ProfileOption = Annotated[
    str | None,
    typer.Option(
        "--profile",
        help="Id профиля из publish.profiles (по умолчанию publish.default).",
    ),
]


def _emit(payload: dict[str, Any], output: OutputFormat, *, text_lines: list[str]) -> None:
    if output is OutputFormat.json:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for line in text_lines:
            typer.echo(line)


def _exit_for(result: PublishResult) -> None:
    if result.status == "ok":
        raise typer.Exit(code=SUCCESS)
    codes = {d.get("code") for d in result.diagnostics}
    if codes & {CODE_IBSRV_MISSING, CODE_IBCMD_MISSING}:
        raise typer.Exit(code=ENV_UNAVAILABLE)
    if codes & {
        CODE_PROJECT,
        CODE_IB_MISSING,
        CODE_PROFILE_UNKNOWN,
        CODE_BACKEND_UNSUPPORTED,
    }:
        raise typer.Exit(code=PROJECT_ERROR)
    if CODE_IBSRV_FAILED in codes:
        raise typer.Exit(code=RUNTIME_FAILURE)
    raise typer.Exit(code=RUNTIME_FAILURE)


def _text(result: PublishResult) -> list[str]:
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

    lines = ["status: ok", f"running: {str(result.running).lower()}"]
    if result.profile_id is not None:
        lines.append(f"profile: {result.profile_id}")
    if result.backend is not None:
        lines.append(f"backend: {result.backend}")
    if result.pid is not None:
        lines.append(f"pid: {result.pid}")
    if result.url is not None:
        lines.append(f"url: {result.url}")
    if result.runtime_path is not None and result.root is not None:
        try:
            rel = result.runtime_path.relative_to(result.root).as_posix()
        except ValueError:
            rel = str(result.runtime_path)
        lines.append(f"runtime: {rel}")
    if result.duration is not None:
        lines.append(f"duration: {result.duration:.3f}s")
    return lines


@app.command("up")
def publish_up(
    ctx: typer.Context,
    profile: ProfileOption = None,
    output: OutputOption = None,
) -> None:
    """Сгенерировать yaml ibsrv (при необходимости) и запустить daemon."""
    result = run_up(Path.cwd(), profile_id=profile)
    _emit(result.to_payload(), resolve_output(ctx, output), text_lines=_text(result))
    _exit_for(result)


@app.command("down")
def publish_down(
    ctx: typer.Context,
    profile: ProfileOption = None,
    output: OutputOption = None,
) -> None:
    """Остановить ibsrv (TERM/KILL) и очистить stale lock.pid."""
    result = run_down(Path.cwd(), profile_id=profile)
    _emit(result.to_payload(), resolve_output(ctx, output), text_lines=_text(result))
    _exit_for(result)


@app.command("status")
def publish_status(
    ctx: typer.Context,
    profile: ProfileOption = None,
    output: OutputOption = None,
) -> None:
    """Статус ibsrv для publish-профиля (pid / url)."""
    result = run_status(Path.cwd(), profile_id=profile)
    _emit(result.to_payload(), resolve_output(ctx, output), text_lines=_text(result))
    _exit_for(result)


@app.command("url")
def publish_url(
    ctx: typer.Context,
    profile: ProfileOption = None,
    output: OutputOption = None,
) -> None:
    """URL веб-клиента из ibsrv.yaml."""
    result = run_url(Path.cwd(), profile_id=profile)
    out = resolve_output(ctx, output)
    if out is OutputFormat.json:
        _emit(result.to_payload(), out, text_lines=_text(result))
    elif result.status == "ok" and result.url:
        typer.echo(result.url)
    else:
        _emit(result.to_payload(), out, text_lines=_text(result))
    _exit_for(result)
