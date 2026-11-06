"""CLI: 1c-dev source …"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any

import typer

from adapters.edtcli import (
    CODE_CONVERT_DIRTY,
    CODE_EDTCLI_COLLISION,
    CODE_EDTCLI_EMPTY_EXPORT,
    CODE_EDTCLI_FAILED,
    CODE_EDTCLI_MISSING,
    CODE_EDTCLI_VERSION,
)
from adapters.source.edt.constants import CODE_LAYOUT_NOT_EDT, CODE_PATH_NOT_EDT_ROOT
from cli.options import ConfigOption
from cli.output import OutputFormat, OutputOption, resolve_output
from core.break_support import BreakSupportResult, run_break_support
from core.break_support.constants import CODE_PROJECT as CODE_BREAK_PROJECT
from core.exit_codes import ENV_UNAVAILABLE, PROJECT_ERROR, RUNTIME_FAILURE, SUCCESS
from core.import_cf.constants import CODE_PROJECT
from core.project.constants import (
    CODE_CONFIG_AMBIGUOUS,
    CODE_CONFIG_UNKNOWN,
    CODE_RUNTIME_AMBIGUOUS,
    CODE_RUNTIME_CONFIG_MISMATCH,
    CODE_RUNTIME_UNKNOWN,
)
from core.source import ConvertResult, run_convert

app = typer.Typer(
    name="source",
    help="Операции над source проекта (break-support, convert).",
    add_completion=False,
    no_args_is_help=True,
)


class ConvertToChoice(str, Enum):
    """Целевой source.format для ``source convert``."""

    edt = "edt"
    xml = "xml"


def _emit(payload: dict[str, Any], output: OutputFormat, *, text_lines: list[str]) -> None:
    if output is OutputFormat.json:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for line in text_lines:
            typer.echo(line)


def _exit_for_break(result: BreakSupportResult) -> None:
    if result.status == "ok":
        raise typer.Exit(code=SUCCESS)
    codes = {d.get("code") for d in result.diagnostics}
    if CODE_BREAK_PROJECT in codes:
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
    _exit_for_break(result)


def _convert_text(result: ConvertResult) -> list[str]:
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
    if result.from_format and result.to_format:
        lines.append(f"format: {result.from_format} → {result.to_format}")
    if result.source_rel is not None:
        lines.append(f"source: {result.source_rel}")
    elif result.source_path is not None and result.root is not None:
        try:
            rel = result.source_path.relative_to(result.root).as_posix()
        except ValueError:
            rel = str(result.source_path)
        lines.append(f"source: {rel}")
    if result.config_id:
        lines.append(f"config: {result.config_id}")
    if result.steps:
        lines.append("steps: " + ", ".join(result.steps))
    return lines


def _exit_for_convert(result: ConvertResult) -> None:
    if result.status == "ok":
        raise typer.Exit(code=SUCCESS)
    codes = {d.get("code") for d in result.diagnostics}
    if codes & {CODE_EDTCLI_MISSING, CODE_EDTCLI_VERSION}:
        raise typer.Exit(code=ENV_UNAVAILABLE)
    if codes & {
        CODE_PROJECT,
        CODE_CONVERT_DIRTY,
        CODE_LAYOUT_NOT_EDT,
        CODE_PATH_NOT_EDT_ROOT,
        CODE_CONFIG_UNKNOWN,
        CODE_RUNTIME_UNKNOWN,
        CODE_CONFIG_AMBIGUOUS,
        CODE_RUNTIME_AMBIGUOUS,
        CODE_RUNTIME_CONFIG_MISMATCH,
    }:
        raise typer.Exit(code=PROJECT_ERROR)
    if codes & {CODE_EDTCLI_FAILED, CODE_EDTCLI_COLLISION, CODE_EDTCLI_EMPTY_EXPORT}:
        raise typer.Exit(code=RUNTIME_FAILURE)
    raise typer.Exit(code=RUNTIME_FAILURE)


@app.command("convert")
def source_convert(
    ctx: typer.Context,
    to: ConvertToChoice = typer.Option(
        ...,
        "--to",
        help="Целевой source.format: edt или xml.",
        case_sensitive=False,
    ),
    config: ConfigOption = None,
    force: bool = typer.Option(
        False,
        "--force",
        help="Идемпотентный no-op, если format уже совпадает с --to.",
    ),
    platform_version: str | None = typer.Option(
        None,
        "--platform-version",
        help="Версия платформы для 1cedtcli import (по умолчанию platform.version манифеста).",
    ),
    output: OutputOption = None,
) -> None:
    """
    Конвертировать source XML ↔ EDT и обновить source.format в манифесте.

    XML→EDT: 1cedtcli import; EDT→XML: 1cedtcli export. Требует 1cedtcli ≥2025.1.
    """
    result = run_convert(
        Path.cwd(),
        to=to.value,
        config_id=config,
        force=force,
        platform_version=platform_version,
    )
    _emit(
        result.to_payload(),
        resolve_output(ctx, output),
        text_lines=_convert_text(result),
    )
    _exit_for_convert(result)
