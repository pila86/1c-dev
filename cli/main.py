"""1c-dev CLI entrypoint."""

from __future__ import annotations

import json

import typer

from cli.build import build_command
from cli.doctor import doctor_command
from cli.init import init_command
from cli.metadata import app as metadata_app
from cli.output import OutputFormat
from cli.project import app as project_app
from core.version import __version__

app = typer.Typer(
    name="1c-dev",
    help="Agent-independent toolchain for 1C development.",
    add_completion=False,
    no_args_is_help=True,
)
app.add_typer(project_app, name="project")
app.add_typer(metadata_app, name="metadata")
app.command("doctor")(doctor_command)
app.command("init")(init_command)
app.command("build")(build_command)


def _version_payload() -> dict[str, str]:
    return {"name": "1c-dev", "version": __version__}


def _emit_version(output: OutputFormat) -> None:
    payload = _version_payload()
    if output is OutputFormat.json:
        typer.echo(json.dumps(payload, ensure_ascii=False))
    else:
        typer.echo(f"1c-dev {payload['version']}")


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        help="Показать версию и выйти.",
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.text,
        "--output",
        help="Формат вывода: text или json.",
    ),
) -> None:
    """1C Dev Runtime CLI."""
    ctx.ensure_object(dict)
    ctx.obj["output"] = output

    if version:
        _emit_version(output)
        raise typer.Exit(code=0)

    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(code=0)


def run() -> None:
    """Console-script entrypoint."""
    app()


if __name__ == "__main__":
    run()
