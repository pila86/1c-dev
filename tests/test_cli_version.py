"""Tests for CLI version output."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from cli.main import app
from core.version import __version__

runner = CliRunner()


def test_version_text() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"1c-dev {__version__}"


def test_version_json() -> None:
    result = runner.invoke(app, ["--output", "json", "--version"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload == {"name": "1c-dev", "version": __version__}
