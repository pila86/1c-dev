"""CLI: 1c-dev yaxunit … (ADR-029 §7a)."""

from __future__ import annotations

from pathlib import Path

import typer

from cli.options import ConfigOption, RuntimeOption
from cli.output import OutputOption
from cli.test import finish
from core.test import ensure_runner

app = typer.Typer(
    name="yaxunit",
    help="Runner YaXUnit: подключение .cfe из user cache в ИБ.",
    add_completion=False,
    no_args_is_help=True,
)


@app.command("ensure")
def ensure_command(
    ctx: typer.Context,
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    output: OutputOption = None,
) -> None:
    """
    Загрузить YAXUNIT из cache (tools sync) в ИБ и снять safe-mode.

    Идемпотентно; не собирает ИБ (сначала `1c-dev build`) и не запускает тесты.
    Нужен только если тесты запускаются в обход `1c-dev test run`.
    """
    result = ensure_runner(
        Path.cwd(),
        config_id=config,
        runtime_id=runtime,
    )
    finish(result, ctx, output)
