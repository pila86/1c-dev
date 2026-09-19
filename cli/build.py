"""CLI: 1c-dev build."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from adapters.platform_ibcmd.constants import (
    CODE_ARTIFACT,
    CODE_IBCMD_MISSING,
    CODE_PROJECT,
    CODE_SOURCE_FORMAT,
    CODE_SOURCE_MISSING,
)
from cli.output import OutputFormat, OutputOption, resolve_output
from core.build import BuildResult, run_build
from core.exit_codes import BUILD_FAILURE, ENV_UNAVAILABLE, PROJECT_ERROR, SUCCESS


def _emit(payload: dict[str, Any], output: OutputFormat, *, text_lines: list[str]) -> None:
    if output is OutputFormat.json:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for line in text_lines:
            typer.echo(line)


def _build_text(result: BuildResult) -> list[str]:
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
    if result.artifact:
        lines.append(f"artifact: {result.artifact}")
    if result.steps:
        lines.append("steps: " + ", ".join(result.steps))
    return lines


def _exit_for(result: BuildResult) -> None:
    if result.status == "ok":
        raise typer.Exit(code=SUCCESS)
    codes = {d.get("code") for d in result.diagnostics}
    if CODE_IBCMD_MISSING in codes:
        raise typer.Exit(code=ENV_UNAVAILABLE)
    if codes & {
        CODE_PROJECT,
        CODE_SOURCE_FORMAT,
        CODE_SOURCE_MISSING,
        CODE_ARTIFACT,
    }:
        raise typer.Exit(code=PROJECT_ERROR)
    raise typer.Exit(code=BUILD_FAILURE)


def build_command(
    ctx: typer.Context,
    artifact: str | None = typer.Option(
        None,
        "--artifact",
        help="Тип артефакта: cf (выгрузка .cf в build/out/).",
    ),
    output: OutputOption = None,
) -> None:
    """Собрать конфигурацию: XML → file IB через ibcmd."""
    result = run_build(Path.cwd(), artifact=artifact)
    _emit(result.to_payload(), resolve_output(ctx, output), text_lines=_build_text(result))
    _exit_for(result)
