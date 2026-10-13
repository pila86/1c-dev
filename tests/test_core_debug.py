"""Unit tests for core.debug + CLI 1c-dev debug (ADR-031 / #140) — mocks, no live platform."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from adapters.debug_http import (
    CODE_DBGS_MISSING,
    CODE_NO_SESSION,
    CODE_WAIT_TIMEOUT,
    PROPERTY_ID_COMMON_MODULE,
    AttachResult,
    BreakpointSpec,
    DebugHttpError,
    DebugTarget,
    EvalResult,
    HttpResponse,
    StackFrame,
    StopEvent,
    VariableValue,
)
from adapters.platform.discovery import DiscoveryResult, PlatformInfo, ToolInfo
from cli.main import app
from core.debug import (
    CODE_PROJECT,
    DebugResult,
    run_attach,
    run_breakpoint_set,
    run_continue,
    run_detach,
    run_evaluate,
    run_force_detach,
    run_reload_metadata,
    run_server_start,
    run_server_status,
    run_server_stop,
    run_stack,
    run_status,
    run_targets,
    run_variables,
    run_wait,
)
from core.debug.state import write_server_state, write_session
from core.exit_codes import ENV_UNAVAILABLE, PROJECT_ERROR, RUNTIME_FAILURE, SUCCESS
from core.runtime import run_start
from core.runtime.state import read_meta
from tests.helpers_project import bootstrap_configuration_project

runner = CliRunner()
SPIKE_OBJECT = "b7e2c4a1-8f3d-4a6e-9c1b-2d5e8f0a3b6c"
SPIKE_TARGET = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _tool(found: bool, path: Path | None = None) -> ToolInfo:
    return ToolInfo(found=found, path=path)


def _discovery(*, dbgs: Path | None = None) -> DiscoveryResult:
    return DiscoveryResult(
        platform=PlatformInfo(found=True, version="8.3.25.1560", path=Path("/opt/1cv8")),
        ibcmd=_tool(True, Path("/fake/ibcmd")),
        onecv8=_tool(True, Path("/fake/1cv8")),
        onecv8c=_tool(False),
        ibsrv=_tool(False),
        webinst=_tool(False),
        dbgs=_tool(dbgs is not None, dbgs),
    )


def _init_project(tmp_path: Path, *, debug_port: int | None = 2550) -> Path:
    target = tmp_path / "shop"
    target.mkdir()
    assert bootstrap_configuration_project(target, name="Shop").status == "ok"
    if debug_port is not None:
        manifest = target / ".1c-dev" / "project.yaml"
        text = manifest.read_text(encoding="utf-8")
        if "debug:" not in text:
            text += (
                "\ndebug:\n"
                f"  host: localhost\n"
                f"  port: {debug_port}\n"
                "  infobaseAlias: DefAlias\n"
            )
            manifest.write_text(text, encoding="utf-8")
    return target


def _fake_session(**methods: Any) -> MagicMock:
    session = MagicMock()
    session.session_id = "sid-test"
    session.attached = True
    session.last_stop = None
    for name, value in methods.items():
        setattr(session, name, value)
    return session


def test_debug_result_to_payload_exit_codes() -> None:
    ok = DebugResult(status="ok", exit_code=SUCCESS, target_id="t1", line_no=10)
    payload = ok.to_payload()
    assert payload["status"] == "ok"
    assert payload["targetId"] == "t1"
    assert payload["lineNo"] == 10
    assert payload["exitCode"] == SUCCESS


def test_server_start_missing_port(tmp_path: Path) -> None:
    target = _init_project(tmp_path, debug_port=None)
    result = run_server_start(
        target,
        discover=lambda: _discovery(dbgs=Path("/fake/dbgs")),
        spawn=lambda _argv, _log: 1,
    )
    assert result.status == "failed"
    assert result.exit_code == PROJECT_ERROR
    assert any(d.get("code") == CODE_PROJECT for d in result.diagnostics)


def test_server_start_dbgs_missing(tmp_path: Path) -> None:
    target = _init_project(tmp_path)
    result = run_server_start(
        target,
        discover=lambda: _discovery(dbgs=None),
    )
    assert result.status == "failed"
    assert result.exit_code == ENV_UNAVAILABLE
    assert any(d.get("code") == CODE_DBGS_MISSING for d in result.diagnostics)


def test_server_start_stop_status_happy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = _init_project(tmp_path)
    alive: dict[int, bool] = {}
    spawned: list[list[str]] = []

    def spawn(argv: list[str], log_path: Path) -> int:
        spawned.append(list(argv))
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # simulate notify file (UTF-16 LE like real dbgs)
        notify = target / ".1c-dev" / "debug" / "server.notify"
        notify.parent.mkdir(parents=True, exist_ok=True)
        notify.write_bytes("ok".encode("utf-16"))
        pid = 9001
        alive[pid] = True
        return pid

    monkeypatch.setattr("core.debug.server._port_free", lambda _h, _p: True)

    def transport(
        url: str, data: bytes, headers: dict[str, str], timeout: float
    ) -> HttpResponse:
        return HttpResponse(200, "<ok/>")

    result = run_server_start(
        target,
        discover=lambda: _discovery(dbgs=Path("/fake/dbgs")),
        spawn=spawn,
        is_alive=lambda pid: alive.get(pid, False),
        transport=transport,
        settle_seconds=0,
        notify_timeout=1.0,
    )
    assert result.status == "ok"
    assert result.running is True
    assert result.pid == 9001
    assert result.port == 2550
    assert result.url == "http://localhost:2550"
    assert any("--port=2550" in a for a in spawned[0])

    status = run_server_status(
        target,
        is_alive=lambda pid: alive.get(pid, False),
        transport=transport,
    )
    assert status.running is True

    stop = run_server_stop(
        target,
        is_alive=lambda pid: alive.get(pid, False),
        terminate_fn=lambda pid: alive.__setitem__(pid, False) or True,
    )
    assert stop.status == "ok"
    assert stop.running is False


def test_attach_detach_with_mock_session(tmp_path: Path) -> None:
    target = _init_project(tmp_path)
    write_server_state(target, pid=1, host="localhost", port=2550)

    def factory(client: Any, **kwargs: Any) -> MagicMock:
        session = _fake_session(
            attach=MagicMock(
                return_value=AttachResult(session_id="sid-1", result="registered")
            ),
            detach=MagicMock(return_value="ok"),
            stop_ping=MagicMock(),
            start_ping=MagicMock(),
        )
        session.session_id = "sid-1"
        return session

    def transport(
        url: str, data: bytes, headers: dict[str, str], timeout: float
    ) -> HttpResponse:
        return HttpResponse(200, "<ok/>")

    attached = run_attach(
        target,
        transport=transport,
        session_factory=factory,
    )
    assert attached.status == "ok"
    assert attached.session_id == "sid-1"
    assert attached.attached is True
    assert (target / ".1c-dev" / "debug" / "session.json").is_file()

    detached = run_detach(target, transport=transport, session_factory=factory)
    assert detached.status == "ok"
    assert detached.attached is False
    assert not (target / ".1c-dev" / "debug" / "session.json").exists()


def test_attach_no_url(tmp_path: Path) -> None:
    target = _init_project(tmp_path, debug_port=None)
    result = run_attach(target)
    assert result.status == "failed"
    assert result.exit_code == RUNTIME_FAILURE


def test_ops_require_session(tmp_path: Path) -> None:
    target = _init_project(tmp_path)
    result = run_targets(target)
    assert result.status == "failed"
    assert any(d.get("code") == CODE_NO_SESSION for d in result.diagnostics)
    assert result.exit_code == RUNTIME_FAILURE


def test_breakpoint_set_and_wait_stack_vars_eval(tmp_path: Path) -> None:
    target = _init_project(tmp_path)
    write_session(target, url="http://localhost:2550", alias="DefAlias", session_id="sid-1")

    stop = StopEvent(
        target_id=SPIKE_TARGET,
        frames=(
            StackFrame(
                object_id=SPIKE_OBJECT,
                property_id=PROPERTY_ID_COMMON_MODULE,
                line_no=42,
                module_name="ОтладкаДемо",
            ),
        ),
    )
    eval_result = EvalResult(
        state="correctly",
        variables=(
            VariableValue(name="Значение", type_name="Строка", presentation="x", value_raw="x"),
        ),
    )

    def factory(client: Any, **kwargs: Any) -> MagicMock:
        session = _fake_session(
            set_breakpoints_by_module=MagicMock(
                return_value=BreakpointSpec(
                    object_id=SPIKE_OBJECT,
                    property_id=PROPERTY_ID_COMMON_MODULE,
                    lines=(42,),
                )
            ),
            wait_for_stop=MagicMock(return_value=stop),
            stack=MagicMock(return_value=list(stop.frames)),
            variables=MagicMock(return_value=eval_result),
            evaluate=MagicMock(return_value=eval_result),
            continue_=MagicMock(return_value="ok"),
            targets=MagicMock(
                return_value=[
                    DebugTarget(target_id=SPIKE_TARGET, target_type="Client", state="Attached")
                ]
            ),
            stop_ping=MagicMock(),
            start_ping=MagicMock(),
            last_stop=stop,
        )
        # resolver used only if real set_breakpoints_by_module — mocked
        session.resolver = SimpleNamespace()
        return session

    bp = run_breakpoint_set(
        target,
        module="ОтладкаДемо",
        module_type="CommonModule",
        lines=[42],
        session_factory=factory,
    )
    assert bp.status == "ok"
    assert bp.breakpoints[0]["lines"] == [42]

    waited = run_wait(target, timeout=1.0, session_factory=factory)
    assert waited.status == "ok"
    assert waited.line_no == 42
    assert waited.target_id == SPIKE_TARGET

    stack = run_stack(target, session_factory=factory)
    assert stack.status == "ok"
    assert len(stack.call_stack) == 1

    variables = run_variables(target, session_factory=factory)
    assert variables.status == "ok"
    assert variables.variables[0]["name"] == "Значение"

    ev = run_evaluate(target, expression="1+1", session_factory=factory)
    assert ev.status == "ok"
    assert ev.expression == "1+1"

    cont = run_continue(target, session_factory=factory)
    assert cont.status == "ok"

    targets = run_targets(target, session_factory=factory)
    assert targets.status == "ok"
    assert targets.targets[0]["targetId"] == SPIKE_TARGET


def test_wait_timeout_exit_4(tmp_path: Path) -> None:
    target = _init_project(tmp_path)
    write_session(target, url="http://localhost:2550", alias="DefAlias", session_id="sid-1")

    def factory(client: Any, **kwargs: Any) -> MagicMock:
        return _fake_session(
            wait_for_stop=MagicMock(
                side_effect=DebugHttpError("timeout", code=CODE_WAIT_TIMEOUT)
            ),
            stop_ping=MagicMock(),
            start_ping=MagicMock(),
        )

    result = run_wait(target, timeout=0.1, session_factory=factory)
    assert result.status == "failed"
    assert result.exit_code == RUNTIME_FAILURE
    assert any(d.get("code") == CODE_WAIT_TIMEOUT for d in result.diagnostics)


def test_force_detach_clears_session(tmp_path: Path) -> None:
    target = _init_project(tmp_path)
    write_session(target, url="http://localhost:2550", alias="DefAlias", session_id="sid-1")

    def factory(client: Any, **kwargs: Any) -> MagicMock:
        return _fake_session(
            force_detach=MagicMock(return_value="ok"),
            stop_ping=MagicMock(),
        )

    result = run_force_detach(target, session_factory=factory)
    assert result.status == "ok"
    assert not (target / ".1c-dev" / "debug" / "session.json").exists()


def test_reload_metadata(tmp_path: Path) -> None:
    target = _init_project(tmp_path)
    # minimal CommonModule under bootstrap source.path src/cf
    modules = target / "src" / "cf" / "CommonModules"
    modules.mkdir(parents=True, exist_ok=True)
    (modules / "ОтладкаДемо.xml").write_text(
        '<?xml version="1.0"?>\n'
        "<MetaDataObject>\n"
        '  <CommonModule uuid="b7e2c4a1-8f3d-4a6e-9c1b-2d5e8f0a3b6c">\n'
        "    <Properties><Name>ОтладкаДемо</Name></Properties>\n"
        "  </CommonModule>\n"
        "</MetaDataObject>\n",
        encoding="utf-8",
    )
    result = run_reload_metadata(target)
    assert result.status == "ok"
    assert result.modules_count is not None
    assert result.modules_count >= 1
    assert (target / ".1c-dev" / "debug" / "modules-cache.json").is_file()


def test_debug_status_summary(tmp_path: Path) -> None:
    target = _init_project(tmp_path)
    write_server_state(target, pid=42, host="localhost", port=2550)
    write_session(target, url="http://localhost:2550", alias="DefAlias", session_id="sid-9")
    alive = {42: True}
    result = run_status(target, is_alive=lambda pid: alive.get(pid, False))
    assert result.status == "ok"
    assert result.attached is True
    assert result.session_id == "sid-9"
    assert result.port == 2550


def test_runtime_start_debug_http_argv(tmp_path: Path) -> None:
    from adapters.platform_ibcmd.constants import IB_MARKER

    target = _init_project(tmp_path)
    ib = target / ".1c-dev" / "runtime" / "main"
    ib.mkdir(parents=True, exist_ok=True)
    (ib / IB_MARKER).write_bytes(b"")

    spawned: list[list[str]] = []
    alive: dict[int, bool] = {}

    def spawn(argv: list[str]) -> int:
        spawned.append(list(argv))
        alive[99] = True
        return 99

    # DebuggerURL from manifest debug.host+port (ADR-031 order)
    result = run_start(
        target,
        debug=True,
        discover=lambda: _discovery(dbgs=Path("/fake/dbgs")),
        spawn=spawn,
        is_alive=lambda pid: alive.get(pid, False),
        settle_seconds=0,
    )
    assert result.status == "ok"
    assert "-http" in spawned[0]
    assert "-attach" in spawned[0]
    assert any(a.startswith('/DebuggerURL"') for a in spawned[0])
    meta = read_meta(target)
    assert meta["debug"]["enabled"] is True
    assert meta["debug"]["debuggerUrl"] == "http://localhost:2550"


def test_cli_debug_server_start_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = _init_project(tmp_path)
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
        lambda: _discovery(dbgs=Path("/fake/dbgs")),
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
    target = _init_project(tmp_path, debug_port=None)
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
