"""Shared CLI output format."""

from __future__ import annotations

from enum import Enum
from typing import Annotated

import typer


class OutputFormat(str, Enum):
    text = "text"
    json = "json"


OutputOption = Annotated[
    OutputFormat | None,
    typer.Option(
        "--output",
        help="Формат вывода: text или json (можно после подкоманды).",
    ),
]


def resolve_output(
    ctx: typer.Context,
    output: OutputFormat | None = None,
) -> OutputFormat:
    """Prefer per-command --output, else root callback, else text."""
    if output is not None:
        return output
    raw = ctx.obj.get("output", OutputFormat.text) if ctx.obj else OutputFormat.text
    if isinstance(raw, OutputFormat):
        return raw
    return OutputFormat(str(raw))
