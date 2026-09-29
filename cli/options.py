"""Shared Typer options for config/runtime selection (#87)."""

from __future__ import annotations

from typing import Annotated

import typer

ConfigOption = Annotated[
    str | None,
    typer.Option(
        "--config",
        help="Id configuration из configurations[] (schema \"2\").",
    ),
]

RuntimeOption = Annotated[
    str | None,
    typer.Option(
        "--runtime",
        help="Id runtime из runtimes[] (schema \"2\").",
    ),
]

ExtensionOption = Annotated[
    str | None,
    typer.Option(
        "--extension",
        help=(
            "Id или name nested extension из configurations[].extensions[] "
            "(metadata.* → src/cfe/…; #112)."
        ),
    ),
]
