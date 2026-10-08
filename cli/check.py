"""CLI: 1c-dev check."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from adapters.platform_ibcmd.constants import (
    CODE_CHECK_FAILED,
    CODE_CHECK_IB_MISSING,
    CODE_CHECK_IBCMD_MISSING,
    CODE_CHECK_ONECV8_MISSING,
    CODE_CHECK_PROJECT,
)
from cli.output import OutputFormat, OutputOption, resolve_output
from core.check import CheckResult, run_check
from core.exit_codes import CHECK_FAILURE, ENV_UNAVAILABLE, PROJECT_ERROR, SUCCESS


def _emit(payload: dict[str, Any], output: OutputFormat, *, text_lines: list[str]) -> None:
    if output is OutputFormat.json:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for line in text_lines:
            typer.echo(line)


def _check_text(result: CheckResult) -> list[str]:
    if result.status != "ok":
        lines = ["status: failed"]
        if result.steps:
            lines.append(f"steps: {', '.join(result.steps)}")
        for diag in result.diagnostics:
            code = diag.get("code", "")
            prefix = f"[{code}] " if code else ""
            loc = ""
            obj = diag.get("object")
            line_no = diag.get("line")
            if obj is not None and line_no is not None:
                col = diag.get("column")
                loc = f" {obj}:{line_no}" + (f":{col}" if col is not None else "")
            lines.append(f"error: {prefix}{diag.get('message', '')}{loc}")
            suggestion = diag.get("suggestion")
            if suggestion:
                lines.append(f"  → {suggestion}")
        return lines

    lines = ["status: ok"]
    if result.steps:
        lines.append(f"steps: {', '.join(result.steps)}")
    if result.duration is not None:
        lines.append(f"duration: {result.duration:.3f}s")
    if result.runtime_path is not None and result.root is not None:
        try:
            rel = result.runtime_path.relative_to(result.root).as_posix()
        except ValueError:
            rel = str(result.runtime_path)
        lines.append(f"runtime: {rel}")
    return lines


def _exit_for(result: CheckResult) -> None:
    if result.status == "ok":
        raise typer.Exit(code=SUCCESS)
    codes = {d.get("code") for d in result.diagnostics}
    if CODE_CHECK_IBCMD_MISSING in codes or CODE_CHECK_ONECV8_MISSING in codes:
        raise typer.Exit(code=ENV_UNAVAILABLE)
    if codes & {CODE_CHECK_PROJECT, CODE_CHECK_IB_MISSING}:
        raise typer.Exit(code=PROJECT_ERROR)
    if CODE_CHECK_FAILED in codes:
        raise typer.Exit(code=CHECK_FAILURE)
    raise typer.Exit(code=CHECK_FAILURE)


def check_command(
    ctx: typer.Context,
    mode: list[str] | None = typer.Option(
        None,
        "--mode",
        help=(
            "Режим /CheckModules (можно несколько раз). "
            "Default: Server. Примеры: Server, ThinClient, WebClient."
        ),
    ),
    output: OutputOption = None,
) -> None:
    """Проверить конфигурацию: ibcmd metadata check + Designer /CheckModules."""
    result = run_check(Path.cwd(), modes=mode or None)
    _emit(result.to_payload(), resolve_output(ctx, output), text_lines=_check_text(result))
    _exit_for(result)
