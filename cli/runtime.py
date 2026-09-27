"""CLI: 1c-dev runtime …"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from adapters.platform_ibcmd.constants import CODE_IBCMD_FAILED
from cli.output import OutputFormat, OutputOption, resolve_output
from core.exit_codes import (
    BUILD_FAILURE,
    ENV_UNAVAILABLE,
    PROJECT_ERROR,
    RUNTIME_FAILURE,
    SUCCESS,
)
from core.import_cf import ImportResult, run_runtime_load
from core.import_cf.constants import (
    CODE_CF_MISSING,
    CODE_IBCMD_MISSING,
    CODE_PROJECT,
)
from core.runtime import (
    CODE_CLIENT_FAILED,
    CODE_IB_MISSING,
    CODE_ONECV8_MISSING,
    RuntimeResult,
    run_start,
    run_status,
    run_stop,
)
from core.runtime import (
    CODE_PROJECT as CODE_RUNTIME_PROJECT,
)

app = typer.Typer(
    name="runtime",
    help="Операции с file IB (runtime).",
    add_completion=False,
    no_args_is_help=True,
)


def _emit(payload: dict[str, Any], output: OutputFormat, *, text_lines: list[str]) -> None:
    if output is OutputFormat.json:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for line in text_lines:
            typer.echo(line)


def _exit_for_load(result: ImportResult) -> None:
    if result.status == "ok":
        raise typer.Exit(code=SUCCESS)
    codes = {d.get("code") for d in result.diagnostics}
    if CODE_IBCMD_MISSING in codes:
        raise typer.Exit(code=ENV_UNAVAILABLE)
    if codes & {CODE_CF_MISSING, CODE_PROJECT}:
        raise typer.Exit(code=PROJECT_ERROR)
    if CODE_IBCMD_FAILED in codes:
        raise typer.Exit(code=BUILD_FAILURE)
    raise typer.Exit(code=BUILD_FAILURE)


def _exit_for_client(result: RuntimeResult) -> None:
    if result.status == "ok":
        raise typer.Exit(code=SUCCESS)
    codes = {d.get("code") for d in result.diagnostics}
    if CODE_ONECV8_MISSING in codes:
        raise typer.Exit(code=ENV_UNAVAILABLE)
    if codes & {CODE_RUNTIME_PROJECT, CODE_IB_MISSING}:
        raise typer.Exit(code=PROJECT_ERROR)
    if CODE_CLIENT_FAILED in codes:
        raise typer.Exit(code=RUNTIME_FAILURE)
    raise typer.Exit(code=RUNTIME_FAILURE)


def _load_text(result: ImportResult) -> list[str]:
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
    return lines


def _client_text(result: RuntimeResult) -> list[str]:
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
    if result.pid is not None:
        lines.append(f"pid: {result.pid}")
    if result.mode is not None:
        lines.append(f"mode: {result.mode}")
    lines.append(f"debug: {str(result.debug_enabled).lower()}")
    if result.runtime_path is not None and result.root is not None:
        try:
            rel = result.runtime_path.relative_to(result.root).as_posix()
        except ValueError:
            rel = str(result.runtime_path)
        lines.append(f"runtime: {rel}")
    if result.duration is not None:
        lines.append(f"duration: {result.duration:.3f}s")
    return lines


@app.command("load")
def runtime_load(
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
    output: OutputOption = None,
) -> None:
    """Загрузить .cf в file IB без выгрузки XML (CF → IB)."""
    result = run_runtime_load(Path.cwd(), from_path=from_path)
    _emit(result.to_payload(), resolve_output(ctx, output), text_lines=_load_text(result))
    _exit_for_load(result)


@app.command("start")
def runtime_start(
    ctx: typer.Context,
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Запустить клиент с /Debug (задел под DAP / M6).",
    ),
    output: OutputOption = None,
) -> None:
    """Запустить толстый клиент 1С (ENTERPRISE) к file IB (detach)."""
    result = run_start(Path.cwd(), debug=debug)
    _emit(result.to_payload(), resolve_output(ctx, output), text_lines=_client_text(result))
    _exit_for_client(result)


@app.command("stop")
def runtime_stop(
    ctx: typer.Context,
    output: OutputOption = None,
) -> None:
    """Остановить ранее запущенный клиент 1С."""
    result = run_stop(Path.cwd())
    _emit(result.to_payload(), resolve_output(ctx, output), text_lines=_client_text(result))
    _exit_for_client(result)


@app.command("status")
def runtime_status_cmd(
    ctx: typer.Context,
    output: OutputOption = None,
) -> None:
    """Статус detached-клиента 1С для file IB."""
    result = run_status(Path.cwd())
    _emit(result.to_payload(), resolve_output(ctx, output), text_lines=_client_text(result))
    _exit_for_client(result)
