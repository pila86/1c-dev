"""Unit tests for core.debug + CLI 1c-dev debug (ADR-031 / #140) — mocks, no live platform."""

from __future__ import annotations

import time
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
    DebugSession,
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
    parse_breakpoint_specs,
    run_attach,
    run_breakpoint_set,
    run_continue,
    run_detach,
    run_evaluate,
    run_force_detach,
    run_pause,
    run_reload_metadata,
    run_server_start,
    run_server_status,
    run_server_stop,
    run_stack,
    run_status,
    run_step_in,
    run_step_out,
    run_step_over,
    run_targets,
    run_variables,
    run_wait,
)
from core.debug.ping import ensure_background_ping, stop_background_ping
from core.debug.state import (
    alive_ping,
    read_session,
    serialize_last_stop,
    write_server_state,
    write_session,
)
from core.exit_codes import ENV_UNAVAILABLE, PROJECT_ERROR, RUNTIME_FAILURE, SUCCESS
from core.runtime import run_start
from core.runtime.state import read_meta
from tests.helpers_project import bootstrap_configuration_project

runner = CliRunner()
SPIKE_OBJECT = "b7e2c4a1-8f3d-4a6e-9c1b-2d5e8f0a3b6c"
SPIKE_TARGET = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


@pytest.fixture(autouse=True)
def _stub_background_ping(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid real ping_worker; track synthetic pids for alive_ping/stop."""
    from adapters.platform_1cv8 import is_running as real_is_running

    fake_pids: set[int] = set()
    next_pid = {"n": 910000}

    def fake_spawn(root: Path, log_path: Path) -> int:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_bytes(b"")
        next_pid["n"] += 1
        pid = next_pid["n"]
        fake_pids.add(pid)
        return pid

    def hybrid_is_running(pid: int) -> bool:
        if pid in fake_pids:
            return True
        return real_is_running(pid)

    def fake_terminate(pid: int, *, timeout: float = 5.0) -> bool:
        fake_pids.discard(pid)
        return True

    monkeypatch.setattr("core.debug.ping.default_spawn_ping", fake_spawn)
    monkeypatch.setattr("core.debug.ping.is_running", hybrid_is_running)
    monkeypatch.setattr("core.debug.ping.terminate", fake_terminate)
    monkeypatch.setattr("core.debug.state.is_running", hybrid_is_running)


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


def _persist_stop(root: Path, stop: StopEvent, *, session_id: str = "sid-1") -> None:
    """Simulate ping_worker writing callStackFormed → session.json lastStop."""
    cur = read_session(root) or {}
    write_session(
        root,
        url=str(cur.get("url") or "http://localhost:2550"),
        alias=str(cur.get("alias") or "DefAlias"),
        session_id=str(cur.get("sessionId") or session_id),
        last_stop=serialize_last_stop(stop),
        last_target_id=stop.target_id or None,
        attached_targets=[stop.target_id] if stop.target_id else None,
    )


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

    fake_targets = [
        DebugTarget(target_id=SPIKE_TARGET, target_type="Client", state="Attached")
    ]

    def factory(client: Any, **kwargs: Any) -> MagicMock:
        session = _fake_session(
            set_breakpoints_by_module=MagicMock(
                return_value=BreakpointSpec(
                    object_id=SPIKE_OBJECT,
                    property_id=PROPERTY_ID_COMMON_MODULE,
                    lines=(42,),
                )
            ),
            stack=MagicMock(return_value=list(stop.frames)),
            variables=MagicMock(return_value=eval_result),
            evaluate=MagicMock(return_value=eval_result),
            continue_=MagicMock(side_effect=lambda *a, **k: _persist_stop(target, stop) or "ok"),
            clear_cached_stop=MagicMock(),
            targets=MagicMock(return_value=fake_targets),
            ensure_targets_attached=MagicMock(return_value=fake_targets),
            stop_ping=MagicMock(),
            start_ping=MagicMock(),
            last_stop=stop,
            _last_stop=stop,
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

    # --file and --module are mutually exclusive
    both = run_breakpoint_set(
        target,
        module="ОтладкаДемо",
        file="Catalogs/Товары/Ext/ObjectModule.bsl",
        lines=[4],
        session_factory=factory,
    )
    assert both.status == "failed"
    assert both.exit_code == 2

    _persist_stop(target, stop)
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
    assert cont.line_no == 42
    assert cont.call_stack

    targets = run_targets(target, session_factory=factory)
    assert targets.status == "ok"
    assert targets.targets[0]["targetId"] == SPIKE_TARGET


def test_wait_timeout_exit_4(tmp_path: Path) -> None:
    target = _init_project(tmp_path)
    write_session(target, url="http://localhost:2550", alias="DefAlias", session_id="sid-1")

    def factory(client: Any, **kwargs: Any) -> MagicMock:
        return _fake_session(clear_cached_stop=MagicMock())

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


def test_parse_breakpoint_specs_merge_and_errors() -> None:
    specs, diags = parse_breakpoint_specs(
        [
            "src/main/Ext/ManagedApplicationModule.bsl:9",
            "src/main/Ext/ManagedApplicationModule.bsl:8",
            "Module.bsl:1,2",
            "bad-no-line",
        ]
    )
    assert len(diags) == 1
    by_file = {s.file: s.lines for s in specs}
    assert by_file["src/main/Ext/ManagedApplicationModule.bsl"] == (9, 8)
    assert by_file["Module.bsl"] == (1, 2)


def test_runtime_start_bp_requires_debug(tmp_path: Path) -> None:
    target = _init_project(tmp_path)
    result = run_start(
        target,
        debug=False,
        breakpoints=["src/main/Ext/ManagedApplicationModule.bsl:9"],
    )
    assert result.status == "failed"
    assert any(d.get("code") == CODE_PROJECT for d in result.diagnostics)


def test_runtime_start_debug_bp_orchestrates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from adapters.platform_ibcmd.constants import IB_MARKER

    target = _init_project(tmp_path)
    ib = target / ".1c-dev" / "runtime" / "main"
    ib.mkdir(parents=True, exist_ok=True)
    (ib / IB_MARKER).write_bytes(b"")

    events: list[str] = []
    boot_calls: list[list[str]] = []
    spawned: list[list[str]] = []
    alive: dict[int, bool] = {}

    def fake_boot(start: Path | None = None, **kwargs: Any) -> DebugResult:
        events.append("boot")
        boot_calls.append(list(kwargs.get("breakpoints") or []))
        return DebugResult(
            status="ok",
            exit_code=SUCCESS,
            root=target,
            url="http://localhost:2550",
            debugger_url="http://localhost:2550",
            session_id="sid-bp",
            attached=True,
            breakpoints=[
                {
                    "file": "src/main/Ext/ManagedApplicationModule.bsl",
                    "lines": [9],
                    "objectId": SPIKE_OBJECT,
                    "propertyId": PROPERTY_ID_COMMON_MODULE,
                }
            ],
        )

    def fake_prepare(start: Path | None = None, **kwargs: Any) -> DebugResult:
        events.append("prepare")
        return DebugResult(status="ok", exit_code=SUCCESS)

    def fake_armed(start: Path | None = None, **kwargs: Any) -> DebugResult:
        events.append("armed")
        return DebugResult(
            status="ok",
            exit_code=SUCCESS,
            targets=[{"targetId": SPIKE_TARGET}],
        )

    monkeypatch.setattr("core.debug.ops.ensure_debug_for_runtime", fake_boot)
    monkeypatch.setattr("core.debug.ops.prepare_debug_for_spawn", fake_prepare)
    monkeypatch.setattr("core.debug.ops.await_debug_targets_armed", fake_armed)

    def spawn(argv: list[str]) -> int:
        events.append("spawn")
        spawned.append(list(argv))
        alive[42] = True
        return 42

    result = run_start(
        target,
        debug=True,
        breakpoints=["src/main/Ext/ManagedApplicationModule.bsl:9"],
        discover=lambda: _discovery(dbgs=Path("/fake/dbgs")),
        spawn=spawn,
        is_alive=lambda pid: alive.get(pid, False),
        settle_seconds=0,
    )
    assert result.status == "ok"
    assert boot_calls == [["src/main/Ext/ManagedApplicationModule.bsl:9"]]
    # reset+daemon BEFORE spawn; start never waits for a stop
    assert events == ["boot", "prepare", "spawn", "armed"]
    assert result.session_id == "sid-bp"
    assert result.targets_armed is True
    assert result.line_no is None
    assert result.breakpoints[0]["lines"] == [9]
    assert "-http" in spawned[0]
    assert any(a.startswith('/DebuggerURL"') for a in spawned[0])


def test_run_start_has_no_wait_parameters() -> None:
    import inspect

    params = inspect.signature(run_start).parameters
    assert "wait_for_stop" not in params
    assert "wait_timeout" not in params


def test_session_lock_and_update_session_keep_daemon_fields(tmp_path: Path) -> None:
    from core.debug.state import reset_session_runtime, update_session

    target = _init_project(tmp_path)
    write_session(
        target,
        url="http://localhost:2550",
        alias="DefAlias",
        session_id="sid-1",
        last_stop={"targetId": "t1", "frames": []},
        attached_targets=["t1"],
    )
    # CLI snapshot without lastStop must not drop the daemon's stop
    write_session(target, url="http://localhost:2550", alias="DefAlias", session_id="sid-1")
    disk = read_session(target) or {}
    assert disk["lastStop"]["targetId"] == "t1"
    assert disk["attachedTargets"] == ["t1"]
    # attached targets are unioned, not replaced
    write_session(
        target,
        url="http://localhost:2550",
        alias="DefAlias",
        session_id="sid-1",
        attached_targets=["t2"],
    )
    assert (read_session(target) or {})["attachedTargets"] == ["t1", "t2"]
    # update_session is a no-op without a session and atomic with one
    update_session(target, lambda d: {**d, "x": 1})
    assert (read_session(target) or {})["x"] == 1
    reset_session_runtime(target)
    after = read_session(target) or {}
    assert "lastStop" not in after and "attachedTargets" not in after
    assert after["sessionId"] == "sid-1"
    # different sessionId starts a fresh record
    write_session(target, url="u", alias="a", session_id="sid-2")
    assert "x" not in (read_session(target) or {})


def test_ping_worker_persists_stop_and_attaches_target_once(tmp_path: Path) -> None:
    from core.debug.ping_worker import _Daemon

    target = _init_project(tmp_path)
    write_session(target, url="http://localhost:2550", alias="DefAlias", session_id="sid-d")
    posts: list[str] = []

    def transport(
        url: str, data: bytes, headers: dict[str, str], timeout: float
    ) -> HttpResponse:
        cmd = url.split("cmd=")[1].split("&")[0]
        posts.append(cmd)
        return HttpResponse(status=200, body="<response/>")

    daemon = _Daemon(target, interval=0.02)
    assert daemon._bootstrap()  # noqa: SLF001
    assert daemon.session is not None
    daemon.session.client._transport = transport  # type: ignore[attr-defined]  # noqa: SLF001
    daemon.attach_target(SPIKE_TARGET)
    daemon.attach_target(SPIKE_TARGET)  # second call is a no-op
    assert posts.count("attachDetachDbgTargets") == 1
    assert (read_session(target) or {})["attachedTargets"] == [SPIKE_TARGET]


def test_wait_returns_immediately_when_already_stopped(tmp_path: Path) -> None:
    target = _init_project(tmp_path)
    write_session(
        target,
        url="http://localhost:2550",
        alias="DefAlias",
        session_id="sid-w",
        last_stop={
            "targetId": SPIKE_TARGET,
            "frames": [
                {
                    "objectId": SPIKE_OBJECT,
                    "propertyId": PROPERTY_ID_COMMON_MODULE,
                    "lineNo": 5,
                    "moduleName": "M",
                    "moduleType": "CommonModule",
                }
            ],
        },
        attached_targets=[SPIKE_TARGET],
    )
    result = run_wait(target, timeout=0.0, client_alive=lambda: True)
    assert result.status == "ok"
    assert result.line_no == 5


def test_wait_fails_fast_when_client_exited(tmp_path: Path) -> None:
    from core.debug.constants import CODE_CLIENT_EXITED

    target = _init_project(tmp_path)
    write_session(target, url="http://localhost:2550", alias="DefAlias", session_id="sid-x")
    t0 = time.perf_counter()
    result = run_wait(target, timeout=30.0, client_alive=lambda: False)
    assert time.perf_counter() - t0 < 5
    assert result.status == "failed"
    assert any(d.get("code") == CODE_CLIENT_EXITED for d in result.diagnostics)


def test_wait_times_out_when_client_alive_without_stop(tmp_path: Path) -> None:
    target = _init_project(tmp_path)
    write_session(target, url="http://localhost:2550", alias="DefAlias", session_id="sid-t")
    result = run_wait(target, timeout=0.2, client_alive=lambda: True)
    assert result.status == "failed"
    assert any(d.get("code") == CODE_WAIT_TIMEOUT for d in result.diagnostics)


def test_wait_fresh_drops_recorded_stop(tmp_path: Path) -> None:
    target = _init_project(tmp_path)
    write_session(
        target,
        url="http://localhost:2550",
        alias="DefAlias",
        session_id="sid-f",
        last_stop={"targetId": SPIKE_TARGET, "frames": []},
    )
    result = run_wait(target, timeout=0.2, fresh=True, client_alive=lambda: True)
    assert result.status == "failed"
    assert "lastStop" not in (read_session(target) or {})


def test_only_pause_carries_experimental_warning(tmp_path: Path) -> None:
    target = _init_project(tmp_path)
    write_session(target, url="http://localhost:2550", alias="DefAlias", session_id="sid-e")

    def experimental(result: Any) -> bool:
        return any(
            "экспериментал" in str(d.get("message"))
            for d in result.diagnostics
            if d.get("severity") == "warning"
        )

    for run in (run_step_in, run_step_over, run_step_out, run_continue):
        result = run(target, wait=False, session_factory=lambda c, **k: _fake_session())
        assert result.status == "ok", run.__name__
        assert not experimental(result), run.__name__
    paused = run_pause(target, wait=False, session_factory=lambda c, **k: _fake_session())
    assert paused.status == "ok"
    assert experimental(paused)


@pytest.mark.parametrize(
    ("run", "label"),
    [
        (run_continue, "continue"),
        (run_step_over, "step-over"),
        (run_step_in, "step-in"),
        (run_step_out, "step-out"),
    ],
)
def test_step_ok_with_warning_when_program_finishes(tmp_path: Path, run: Any, label: str) -> None:
    """Клиент завершился во время шага (например, step-out из верхнего кадра) — не ошибка."""
    from core.debug.constants import CODE_CLIENT_EXITED

    target = _init_project(tmp_path)
    write_session(target, url="http://localhost:2550", alias="DefAlias", session_id="sid-fin")
    result = run(
        target,
        timeout=5.0,
        client_alive=lambda: False,
        session_factory=lambda c, **k: _fake_session(),
    )
    assert result.status == "ok", result.to_payload()
    assert not result.call_stack
    exited = [d for d in result.diagnostics if d.get("code") == CODE_CLIENT_EXITED]
    assert exited
    assert label in str(exited[0].get("message"))
    assert "lastStop" not in (read_session(target) or {})


def test_pause_fails_when_client_exited(tmp_path: Path) -> None:
    from core.debug.constants import CODE_CLIENT_EXITED

    target = _init_project(tmp_path)
    write_session(target, url="http://localhost:2550", alias="DefAlias", session_id="sid-p")
    result = run_pause(
        target,
        timeout=5.0,
        client_alive=lambda: False,
        session_factory=lambda c, **k: _fake_session(),
    )
    assert result.status == "failed"
    assert any(d.get("code") == CODE_CLIENT_EXITED for d in result.diagnostics)


def test_teardown_debug_clears_ping_session_and_own_server(tmp_path: Path) -> None:
    from core.debug.ops import has_debug_state, teardown_debug
    from core.debug.state import read_server_pid, write_server_state

    target = _init_project(tmp_path)
    write_session(target, url="http://localhost:2550", alias="DefAlias", session_id="sid-td")
    ensure_background_ping(target)
    write_server_state(target, pid=920001, host="localhost", port=2550)
    assert has_debug_state(target)
    terminated: list[int] = []

    def term(pid: int, *, timeout: float = 5.0) -> bool:
        terminated.append(pid)
        return True

    result = teardown_debug(
        target,
        transport=lambda *a, **k: HttpResponse(status=200, body="<response/>"),
        is_alive=lambda pid: pid not in terminated and pid != 0 and pid > 900000,
        terminate_fn=term,
    )
    assert result.status == "ok"
    assert read_session(target) is None
    assert read_server_pid(target) is None
    assert 920001 in terminated
    assert not has_debug_state(target)
    # idempotent
    again = teardown_debug(target, is_alive=lambda pid: False, terminate_fn=term)
    assert again.status == "ok"


def test_runtime_stop_runs_debug_teardown(tmp_path: Path) -> None:
    from core.runtime import run_stop

    target = _init_project(tmp_path)
    write_session(target, url="http://localhost:2550", alias="DefAlias", session_id="sid-rs")
    ensure_background_ping(target)
    result = run_stop(
        target,
        is_alive=lambda pid: False,
        terminate_fn=lambda pid, **k: True,
    )
    assert result.status == "ok"
    assert read_session(target) is None
    assert not (target / ".1c-dev" / "debug" / "ping.pid").exists()


def test_cli_runtime_start_bp_help() -> None:
    result = runner.invoke(app, ["runtime", "start", "--help"])
    assert result.exit_code == 0
    assert "--bp" in result.output
    assert "--wait" not in result.output
    assert "--debug" in result.output


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


def test_wait_persists_last_stop_for_next_cli_process(tmp_path: Path) -> None:
    """Short-lived CLI: wait picks up lastStop; stack/continue restore from disk."""
    target = _init_project(tmp_path)
    stop = StopEvent(
        target_id="tgt-persist",
        frames=(
            StackFrame(
                object_id=SPIKE_OBJECT,
                property_id=PROPERTY_ID_COMMON_MODULE,
                line_no=9,
                module_name="ManagedApplicationModule",
            ),
        ),
    )
    write_session(
        target,
        url="http://localhost:2550",
        alias="DefAlias",
        session_id="sid-persist",
        last_stop=serialize_last_stop(stop),
        last_target_id="tgt-persist",
        attached_targets=["tgt-persist"],
    )

    def factory(client: Any, **kwargs: Any) -> MagicMock:
        sess = _fake_session(clear_cached_stop=MagicMock())
        sess.session_id = kwargs.get("session_id", "sid-persist")
        return sess

    waited = run_wait(
        target, timeout=1.0, session_factory=factory, client_alive=lambda: True
    )
    assert waited.status == "ok"
    assert waited.line_no == 9
    disk = read_session(target) or {}
    assert "lastStop" in disk
    assert disk["lastStop"]["targetId"] == "tgt-persist"
    assert disk["attachedTargets"] == ["tgt-persist"]

    def _ok_transport(
        url: str, data: bytes, headers: dict[str, str], timeout: float
    ) -> HttpResponse:
        return HttpResponse(status=200, body="<response><result>ok</result></response>")

    # New process: default DebugSession hydrated from session.json
    stacked = run_stack(target, transport=_ok_transport)
    assert stacked.status == "ok"
    assert stacked.line_no == 9
    assert stacked.call_stack[0]["moduleName"] == "ManagedApplicationModule"

    continued = run_continue(target, transport=_ok_transport, wait=False)
    assert continued.status == "ok"
    after = read_session(target) or {}
    assert "lastStop" not in after


def test_step_in_waits_and_persists_stop(tmp_path: Path) -> None:
    """step-in keeps bg ping up and polls lastStop written after the step."""
    target = _init_project(tmp_path)
    write_session(target, url="http://localhost:2550", alias="DefAlias", session_id="sid-1")
    stop = StopEvent(
        target_id=SPIKE_TARGET,
        frames=(
            StackFrame(
                object_id=SPIKE_OBJECT,
                property_id=PROPERTY_ID_COMMON_MODULE,
                line_no=4,
                module_name="ОтладкаДемо",
                module_type="CommonModule",
            ),
        ),
    )
    order: list[str] = []
    clear_cached_stop = MagicMock(side_effect=lambda: order.append("clear"))
    step_in = MagicMock(
        side_effect=lambda *a, **k: (
            order.append("step"),
            _persist_stop(target, stop),
            "ok",
        )[-1]
    )

    def factory(client: Any, **kwargs: Any) -> MagicMock:
        return _fake_session(
            step_in=step_in,
            clear_cached_stop=clear_cached_stop,
            last_stop=None,
            _last_stop=None,
            _attached_targets={SPIKE_TARGET},
            _last_target_id=SPIKE_TARGET,
        )

    result = run_step_in(target, timeout=1.0, session_factory=factory)
    assert result.status == "ok"
    assert result.line_no == 4
    assert result.module_name == "ОтладкаДемо"
    assert result.call_stack[0]["moduleName"] == "ОтладкаДемо"
    step_in.assert_called_once()
    clear_cached_stop.assert_called()
    # Keepalive stays up: clear → step → worker (simulated) writes lastStop.
    assert order == ["clear", "step"]
    disk = read_session(target) or {}
    assert disk.get("lastStop", {}).get("targetId") == SPIKE_TARGET
    assert result.ping_running is True


def test_step_over_waits_and_sends_step_action(tmp_path: Path) -> None:
    """step-over uses platform action Step and waits for next stop."""
    target = _init_project(tmp_path)
    write_session(target, url="http://localhost:2550", alias="DefAlias", session_id="sid-1")
    before = StopEvent(
        target_id=SPIKE_TARGET,
        frames=(
            StackFrame(
                object_id=SPIKE_OBJECT,
                property_id=PROPERTY_ID_COMMON_MODULE,
                line_no=4,
                module_name="ОтладкаДемо",
                module_type="CommonModule",
            ),
        ),
    )
    after = StopEvent(
        target_id=SPIKE_TARGET,
        frames=(
            StackFrame(
                object_id=SPIKE_OBJECT,
                property_id=PROPERTY_ID_COMMON_MODULE,
                line_no=5,
                module_name="ОтладкаДемо",
                module_type="CommonModule",
            ),
        ),
    )
    step_over = MagicMock(
        side_effect=lambda *a, **k: (_persist_stop(target, after), "ok")[-1]
    )

    def factory(client: Any, **kwargs: Any) -> MagicMock:
        return _fake_session(
            step_over=step_over,
            clear_cached_stop=MagicMock(),
            last_stop=before,
            _last_stop=before,
            _attached_targets={SPIKE_TARGET},
            _last_target_id=SPIKE_TARGET,
        )

    result = run_step_over(target, timeout=1.0, session_factory=factory)
    assert result.status == "ok"
    assert result.line_no == 5
    step_over.assert_called_once_with(SPIKE_TARGET)


def test_step_in_uses_stopped_target_not_stale_last_target(tmp_path: Path) -> None:
    """StepIn must use lastStop.targetId (EDT), not a sibling lastTargetId."""
    other = "cccccccc-dddd-eeee-ffff-000000000000"
    target = _init_project(tmp_path)
    # Stale lastTargetId on disk (as after buggy all-targets re-attach); no lastStop.
    write_session(
        target,
        url="http://localhost:2550",
        alias="DefAlias",
        session_id="sid-1",
        last_target_id=other,
    )
    before_stop = StopEvent(
        target_id=SPIKE_TARGET,
        frames=(
            StackFrame(
                object_id=SPIKE_OBJECT,
                property_id=PROPERTY_ID_COMMON_MODULE,
                line_no=4,
                module_name="ОтладкаДемо",
                module_type="CommonModule",
            ),
        ),
    )
    after_stop = StopEvent(
        target_id=SPIKE_TARGET,
        frames=(
            StackFrame(
                object_id=SPIKE_OBJECT,
                property_id=PROPERTY_ID_COMMON_MODULE,
                line_no=5,
                module_name="ОтладкаДемо",
                module_type="CommonModule",
            ),
        ),
    )
    step_in = MagicMock(
        side_effect=lambda *a, **k: (_persist_stop(target, after_stop), "ok")[-1]
    )

    def factory(client: Any, **kwargs: Any) -> MagicMock:
        return _fake_session(
            step_in=step_in,
            clear_cached_stop=MagicMock(),
            last_stop=before_stop,
            _last_stop=before_stop,
            _attached_targets={SPIKE_TARGET, other},
            _last_target_id=other,
            _breakpoints=[],
            resolver=None,
        )

    result = run_step_in(target, timeout=1.0, session_factory=factory)
    assert result.status == "ok"
    step_in.assert_called_once_with(SPIKE_TARGET)


def test_background_ping_ensure_and_stop(tmp_path: Path) -> None:
    target = _init_project(tmp_path)
    missing = ensure_background_ping(target)
    assert missing.status == "failed"
    assert any(d.get("code") == CODE_NO_SESSION for d in missing.diagnostics)

    write_session(target, url="http://localhost:2550", alias="DefAlias", session_id="sid-ping")
    started = ensure_background_ping(target)
    assert started.status == "ok"
    assert started.ping_running is True
    assert started.ping_pid is not None
    running, pid, meta = alive_ping(target)
    assert running and pid == started.ping_pid
    assert meta.get("sessionId") == "sid-ping"

    again = ensure_background_ping(target)
    assert again.status == "ok"
    assert again.ping_pid == started.ping_pid

    stopped = stop_background_ping(target)
    assert stopped.status == "ok"
    assert stopped.ping_running is False
    assert not alive_ping(target)[0]


def test_wait_starts_background_ping(tmp_path: Path) -> None:
    target = _init_project(tmp_path)
    write_session(target, url="http://localhost:2550", alias="DefAlias", session_id="sid-1")
    stop = StopEvent(
        target_id=SPIKE_TARGET,
        frames=(
            StackFrame(
                object_id=SPIKE_OBJECT,
                property_id=PROPERTY_ID_COMMON_MODULE,
                line_no=8,
                module_name="ОтладкаДемо",
                module_type="CommonModule",
            ),
        ),
    )
    _persist_stop(target, stop)

    def factory(client: Any, **kwargs: Any) -> MagicMock:
        return _fake_session(clear_cached_stop=MagicMock(), last_stop=stop, _last_stop=stop)

    waited = run_wait(target, timeout=1.0, session_factory=factory)
    assert waited.status == "ok"
    assert waited.ping_running is True
    assert waited.ping_pid is not None


def test_cli_debug_ping_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = _init_project(tmp_path)
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


def test_ping_worker_persists_last_stop(tmp_path: Path) -> None:
    from core.debug.ping_worker import persist_stop_from_ping_body

    target = _init_project(tmp_path)
    write_session(target, url="http://localhost:2550", alias="DefAlias", session_id="sid-w")
    body = f"""
    <response>
      <callStackFormed>
        <targetID><id>{SPIKE_TARGET}</id></targetID>
        <callStack>
          <moduleID>
            <objectID>{SPIKE_OBJECT}</objectID>
            <propertyID>{PROPERTY_ID_COMMON_MODULE}</propertyID>
          </moduleID>
          <lineNo>8</lineNo>
        </callStack>
      </callStackFormed>
    </response>
    """
    assert persist_stop_from_ping_body(target, body) is True
    disk = read_session(target) or {}
    assert disk["lastStop"]["targetId"] == SPIKE_TARGET
    assert disk["lastStop"]["frames"][0]["lineNo"] == 8


def test_wait_picks_up_last_stop_written_by_worker(tmp_path: Path) -> None:
    """After continue, bg ping may land stop on disk before CLI wait starts."""
    target = _init_project(tmp_path)
    stop = StopEvent(
        target_id=SPIKE_TARGET,
        frames=(
            StackFrame(
                object_id=SPIKE_OBJECT,
                property_id=PROPERTY_ID_COMMON_MODULE,
                line_no=8,
                module_name="ОтладкаДемо",
                module_type="CommonModule",
            ),
        ),
    )
    write_session(
        target,
        url="http://localhost:2550",
        alias="DefAlias",
        session_id="sid-1",
        last_stop=serialize_last_stop(stop),
        last_target_id=SPIKE_TARGET,
    )

    def factory(client: Any, **kwargs: Any) -> DebugSession:
        return DebugSession(
            client,
            alias=kwargs.get("alias") or "DefAlias",
            session_id=kwargs.get("session_id") or "sid-1",
            resolver=kwargs.get("resolver"),
            auto_attach_types=kwargs.get("auto_attach_types"),
        )

    def transport(url: str, data: bytes, headers: dict[str, str], timeout: float) -> HttpResponse:
        return HttpResponse(status=200, body="")

    waited = run_wait(target, timeout=0.2, session_factory=factory, transport=transport)
    assert waited.status == "ok"
    assert waited.line_no == 8
    assert waited.target_id == SPIKE_TARGET


def test_eval_result_delivered_via_ping_is_read_from_disk(tmp_path: Path) -> None:
    """dbgs answers evalExpr with an empty body when a ping is parked; the daemon
    stores the ``exprEvaluated`` body and ``run_evaluate`` picks it up."""
    from core.debug.state import write_eval_result

    target = _init_project(tmp_path)
    write_session(
        target,
        url="http://localhost:2550",
        alias="DefAlias",
        session_id="sid-ev",
        last_stop={"targetId": SPIKE_TARGET, "frames": []},
        attached_targets=[SPIKE_TARGET],
    )
    late = (
        "<response><evalExprResBaseData><evalResultState>correctly</evalResultState>"
        "<expressionResultID>{rid}</expressionResultID><typeName>Число</typeName>"
        "<pres>ODQ=</pres></evalExprResBaseData></response>"
    )

    def transport(
        url: str, data: bytes, headers: dict[str, str], timeout: float
    ) -> HttpResponse:
        text = data.decode("utf-8")
        marker = "<calc:expressionResultID>"
        rid = text.split(marker)[1].split("</")[0]
        write_eval_result(target, rid, late.format(rid=rid))  # daemon side
        return HttpResponse(status=200, body="<response/>")  # empty POST body

    result = run_evaluate(target, expression="Результат", transport=transport)
    assert result.status == "ok"
    assert result.eval_state == "correctly"
    assert result.result == "84"
