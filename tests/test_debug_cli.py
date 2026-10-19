"""CLI `1c-dev debug` / `runtime start --bp` (CliRunner, mocks)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from adapters.debug_http import (
    HttpResponse,
)
from cli.main import app
from core.debug.state import (
    write_session,
)
from core.exit_codes import RUNTIME_FAILURE, SUCCESS
from tests.helpers_debug import (
    init_project,
    make_discovery,
)

pytestmark = pytest.mark.usefixtures("stub_background_ping")

runner = CliRunner()


def test_cli_runtime_start_bp_help() -> None:
    result = runner.invoke(app, ["runtime", "start", "--help"])
    assert result.exit_code == 0
    # Rich may insert ANSI mid-token (e.g. styled "--bp") when COLUMNS is set (CI).
    plain = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", result.stdout)
    assert "--bp" in plain
    assert "--wait" not in plain
    assert "--debug" in plain


def test_cli_debug_server_start_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = init_project(tmp_path)
    monkeypatch.chdir(target)
    monkeypatch.setattr("core.debug.server._port_free", lambda _h, _p: True)

    alive: dict[int, bool] = {}

    def spawn(argv: list[str], log_path: Path) -> int:
        notify = target / ".1c-dev" / "debug" / "server.notify"
        notify.parent.mkdir(parents=True, exist_ok=True)
        notify.write_bytes(b"ok")
        alive[77] = True
        return 77

    monkeypatch.setattr(
        "core.debug.server.discover_environment",
        lambda: make_discovery(dbgs=Path("/fake/dbgs")),
    )
    monkeypatch.setattr("core.debug.server.default_spawn_dbgs", spawn)
    monkeypatch.setattr(
        "core.debug.server.is_running",
        lambda pid: alive.get(pid, False),
    )
    monkeypatch.setattr(
        "core.debug.server.DebugHttpClient.test",
        lambda self: HttpResponse(200, "<ok/>"),
    )

    result = runner.invoke(app, ["debug", "server", "start", "--output", "json"])
    assert result.exit_code == SUCCESS, result.output
    assert '"status": "ok"' in result.output
    assert '"port": 2550' in result.output


def test_cli_debug_attach_no_session_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = init_project(tmp_path, debug_port=None)
    monkeypatch.chdir(target)
    result = runner.invoke(app, ["debug", "targets", "--output", "json"])
    assert result.exit_code == RUNTIME_FAILURE
    assert "1CD003" in result.output


def test_cli_debug_help() -> None:
    result = runner.invoke(app, ["debug", "--help"])
    assert result.exit_code == 0
    assert "attach" in result.output
    assert "server" in result.output
    assert "breakpoint" in result.output


def test_cli_debug_ping_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = init_project(tmp_path)
    write_session(target, url="http://localhost:2550", alias="DefAlias", session_id="sid-cli")
    monkeypatch.chdir(target)
    r = runner.invoke(app, ["debug", "ping", "start", "--output", "json"])
    assert r.exit_code == 0, r.stdout
    assert '"pingRunning": true' in r.stdout
    r2 = runner.invoke(app, ["debug", "ping", "status", "--output", "json"])
    assert r2.exit_code == 0
    assert '"pingRunning": true' in r2.stdout
    r3 = runner.invoke(app, ["debug", "ping", "stop", "--output", "json"])
    assert r3.exit_code == 0
    assert '"pingRunning": false' in r3.stdout
