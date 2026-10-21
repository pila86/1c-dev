"""core.debug: server / attach / detach / status / teardown (mocks)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from adapters.debug_http import (
    CODE_DBGS_MISSING,
    CODE_NO_SESSION,
    AttachResult,
    HttpResponse,
)
from core.debug import (
    CODE_PROJECT,
    DebugResult,
    run_attach,
    run_detach,
    run_force_detach,
    run_reload_metadata,
    run_server_start,
    run_server_status,
    run_server_stop,
    run_status,
    run_targets,
)
from core.debug.ping import ensure_background_ping
from core.debug.state import (
    read_session,
    write_server_state,
    write_session,
)
from core.exit_codes import ENV_UNAVAILABLE, PROJECT_ERROR, RUNTIME_FAILURE, SUCCESS
from tests.helpers_debug import (
    fake_session,
    init_project,
    make_discovery,
)

pytestmark = pytest.mark.usefixtures("stub_background_ping")


def test_debug_result_to_payload_exit_codes() -> None:
    ok = DebugResult(status="ok", exit_code=SUCCESS, target_id="t1", line_no=10)
    payload = ok.to_payload()
    assert payload["status"] == "ok"
    assert payload["targetId"] == "t1"
    assert payload["lineNo"] == 10
    assert payload["exitCode"] == SUCCESS


def test_server_start_missing_port(tmp_path: Path) -> None:
    target = init_project(tmp_path, debug_port=None)
    result = run_server_start(
        target,
        discover=lambda: make_discovery(dbgs=Path("/fake/dbgs")),
        spawn=lambda _argv, _log: 1,
    )
    assert result.status == "failed"
    assert result.exit_code == PROJECT_ERROR
    assert any(d.get("code") == CODE_PROJECT for d in result.diagnostics)


def test_server_start_dbgs_missing(tmp_path: Path) -> None:
    target = init_project(tmp_path)
    result = run_server_start(
        target,
        discover=lambda: make_discovery(dbgs=None),
    )
    assert result.status == "failed"
    assert result.exit_code == ENV_UNAVAILABLE
    assert any(d.get("code") == CODE_DBGS_MISSING for d in result.diagnostics)


def test_server_start_stop_status_happy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = init_project(tmp_path)
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

    def transport(url: str, data: bytes, headers: dict[str, str], timeout: float) -> HttpResponse:
        return HttpResponse(200, "<ok/>")

    result = run_server_start(
        target,
        discover=lambda: make_discovery(dbgs=Path("/fake/dbgs")),
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
    target = init_project(tmp_path)
    write_server_state(target, pid=1, host="localhost", port=2550)

    def factory(client: Any, **kwargs: Any) -> MagicMock:
        session = fake_session(
            attach=MagicMock(return_value=AttachResult(session_id="sid-1", result="registered")),
            detach=MagicMock(return_value="ok"),
            stop_ping=MagicMock(),
            start_ping=MagicMock(),
        )
        session.session_id = "sid-1"
        return session

    def transport(url: str, data: bytes, headers: dict[str, str], timeout: float) -> HttpResponse:
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
    target = init_project(tmp_path, debug_port=None)
    result = run_attach(target)
    assert result.status == "failed"
    assert result.exit_code == RUNTIME_FAILURE


def test_ops_require_session(tmp_path: Path) -> None:
    target = init_project(tmp_path)
    result = run_targets(target)
    assert result.status == "failed"
    assert any(d.get("code") == CODE_NO_SESSION for d in result.diagnostics)
    assert result.exit_code == RUNTIME_FAILURE


def test_force_detach_clears_session(tmp_path: Path) -> None:
    target = init_project(tmp_path)
    write_session(target, url="http://localhost:2550", alias="DefAlias", session_id="sid-1")

    def factory(client: Any, **kwargs: Any) -> MagicMock:
        return fake_session(
            force_detach=MagicMock(return_value="ok"),
            stop_ping=MagicMock(),
        )

    result = run_force_detach(target, session_factory=factory)
    assert result.status == "ok"
    assert not (target / ".1c-dev" / "debug" / "session.json").exists()


def test_reload_metadata(tmp_path: Path) -> None:
    target = init_project(tmp_path)
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
    target = init_project(tmp_path)
    write_server_state(target, pid=42, host="localhost", port=2550)
    write_session(target, url="http://localhost:2550", alias="DefAlias", session_id="sid-9")
    alive = {42: True}
    result = run_status(target, is_alive=lambda pid: alive.get(pid, False))
    assert result.status == "ok"
    assert result.attached is True
    assert result.session_id == "sid-9"
    assert result.port == 2550


def test_teardown_debug_clears_ping_session_and_own_server(tmp_path: Path) -> None:
    from core.debug.ops import has_debug_state, teardown_debug
    from core.debug.state import read_server_pid, write_server_state

    target = init_project(tmp_path)
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
