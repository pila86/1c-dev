"""CLI: 1c-dev source …"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from cli.output import OutputFormat, OutputOption, resolve_output
from core.break_support import BreakSupportResult, run_break_support
from core.break_support.constants import CODE_PROJECT
from core.exit_codes import PROJECT_ERROR, SUCCESS

app = typer.Typer(
    name="source",
    help="Операции над XML source проекта.",
    add_completion=False,
    no_args_is_help=True,
)


def _emit(payload: dict[str, Any], output: OutputFormat, *, text_lines: list[str]) -> None:
    if output is OutputFormat.json:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for line in text_lines:
            typer.echo(line)


def _exit_for(result: BreakSupportResult) -> None:
    if result.status == "ok":
        raise typer.Exit(code=SUCCESS)
    codes = {d.get("code") for d in result.diagnostics}
    if CODE_PROJECT in codes:
        raise typer.Exit(code=PROJECT_ERROR)
    raise typer.Exit(code=PROJECT_ERROR)


def _break_support_text(result: BreakSupportResult) -> list[str]:
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
    if result.removed:
        lines.append("removed: " + ", ".join(result.removed))
    for diag in result.diagnostics:
        code = diag.get("code", "")
        prefix = f"[{code}] " if code else ""
        sev = diag.get("severity", "info")
        lines.append(f"{sev}: {prefix}{diag.get('message', '')}")
    return lines


@app.command("break-support")
def source_break_support(
    ctx: typer.Context,
    output: OutputOption = None,
) -> None:
    """
    Снять конфигурацию с поддержки: удалить ParentConfigurations* из source.path.

    Та же strip-логика, что у configuration import --break-support, без повторного import.
    Идемпотентно. Теряется возможность штатного обновления от поставщика.
    """
    result = run_break_support(Path.cwd())
    _emit(
        result.to_payload(),
        resolve_output(ctx, output),
        text_lines=_break_support_text(result),
    )
    _exit_for(result)
