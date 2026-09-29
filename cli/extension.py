"""CLI: 1c-dev extension … (ADR-023 / #88)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from adapters.platform_ibcmd.constants import CODE_IBCMD_FAILED, CODE_IBCMD_MISSING
from cli.options import ConfigOption, RuntimeOption
from cli.output import OutputFormat, OutputOption, resolve_output
from core.exit_codes import ENV_UNAVAILABLE, PROJECT_ERROR, RUNTIME_FAILURE, SUCCESS
from core.extension import ExtensionListResult, add_extension, run_extension_list
from core.extension.list import CODE_IB_MISSING
from core.project.result import ProjectResult

app = typer.Typer(
    name="extension",
    help="Операции с расширениями конфигурации.",
    add_completion=False,
    no_args_is_help=True,
)


def _emit(payload: dict[str, Any], output: OutputFormat, *, text_lines: list[str]) -> None:
    if output is OutputFormat.json:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for line in text_lines:
            typer.echo(line)


def _add_text(result: ProjectResult) -> list[str]:
    if result.status != "ok":
        lines = ["status: error"]
        for diag in result.diagnostics:
            code = diag.get("code", "")
            prefix = f"[{code}] " if code else ""
            lines.append(f"error: {prefix}{diag.get('message', '')}")
            suggestion = diag.get("suggestion")
            if suggestion:
                lines.append(f"  → {suggestion}")
        return lines
    lines = ["status: ok"]
    if result.root is not None:
        lines.append(f"root: {result.root}")
    if result.created:
        lines.append("created:")
        for item in result.created:
            lines.append(f"  - {item}")
    if result.updated:
        lines.append("updated:")
        for item in result.updated:
            lines.append(f"  - {item}")
    return lines


def _list_text(result: ExtensionListResult) -> list[str]:
    if result.status != "ok":
        lines = ["status: error"]
        for diag in result.diagnostics:
            code = diag.get("code", "")
            prefix = f"[{code}] " if code else ""
            lines.append(f"error: {prefix}{diag.get('message', '')}")
            suggestion = diag.get("suggestion")
            if suggestion:
                lines.append(f"  → {suggestion}")
        return lines
    lines = ["status: ok"]
    if result.runtime_path is not None and result.root is not None:
        try:
            rel = result.runtime_path.relative_to(result.root).as_posix()
        except ValueError:
            rel = str(result.runtime_path)
        lines.append(f"runtime: {rel}")
    if not result.extensions:
        lines.append("extensions: (none)")
    else:
        lines.append("extensions:")
        for ext in result.extensions:
            lines.append(f"  - {ext.name}")
    return lines


@app.command("add")
def extension_add_command(
    ctx: typer.Context,
    ext_id: str | None = typer.Option(
        None,
        "--id",
        help="Id расширения в манифесте и каталог/файл src/cfe/<id>.",
    ),
    name: str | None = typer.Option(
        None,
        "--name",
        help="Имя расширения для ibcmd --extension (по умолчанию = --id).",
    ),
    purpose: str = typer.Option(
        "product",
        "--purpose",
        help="purpose: product | tests | other.",
    ),
    from_cfe: Path | None = typer.Option(
        None,
        "--from",
        help=(
            "Путь к .cfe: выгрузить XML в src/cfe/<id>/ "
            "(load → apply → export) и зарегистрировать format=xml."
        ),
        exists=False,
        dir_okay=False,
        file_okay=True,
        resolve_path=False,
    ),
    config: ConfigOption = None,
    force: bool = typer.Option(
        False,
        "--force",
        help="Перезаписать исходники расширения, если каталог уже есть.",
    ),
    output: OutputOption = None,
) -> None:
    """Добавить расширение в configuration-проект (XML scaffold или --from .cfe → XML)."""
    result = add_extension(
        Path.cwd(),
        ext_id=ext_id,
        name=name,
        purpose=purpose,
        config_id=config,
        force=force,
        from_cfe=from_cfe,
    )
    payload = result.to_payload(include_manifest=False)
    _emit(payload, resolve_output(ctx, output), text_lines=_add_text(result))
    raise typer.Exit(code=SUCCESS if result.status == "ok" else PROJECT_ERROR)


@app.command("list")
def extension_list_command(
    ctx: typer.Context,
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    output: OutputOption = None,
) -> None:
    """Список расширений, установленных в выбранной file IB."""
    result = run_extension_list(
        Path.cwd(),
        config_id=config,
        runtime_id=runtime,
    )
    payload = result.to_payload()
    _emit(payload, resolve_output(ctx, output), text_lines=_list_text(result))
    if result.status == "ok":
        raise typer.Exit(code=SUCCESS)
    codes = {d.get("code") for d in result.diagnostics}
    if CODE_IBCMD_MISSING in codes:
        raise typer.Exit(code=ENV_UNAVAILABLE)
    if CODE_IB_MISSING in codes or CODE_IBCMD_FAILED in codes:
        raise typer.Exit(code=RUNTIME_FAILURE)
    raise typer.Exit(code=PROJECT_ERROR)
