"""core.debug: background ping, session.json, eval-result через диск."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from adapters.debug_http import (
    CODE_NO_SESSION,
    PROPERTY_ID_COMMON_MODULE,
    DebugSession,
    HttpResponse,
    StackFrame,
    StopEvent,
)
from core.debug import (
    run_evaluate,
    run_wait,
)
from core.debug.ping import ensure_background_ping, stop_background_ping
from core.debug.state import (
    alive_ping,
    read_session,
    serialize_last_stop,
    write_session,
)
from tests.helpers_debug import (
    SPIKE_OBJECT,
    SPIKE_TARGET,
    fake_session,
    init_project,
    persist_stop,
)

pytestmark = pytest.mark.usefixtures("stub_background_ping")


def test_session_lock_and_update_session_keep_daemon_fields(tmp_path: Path) -> None:
    from core.debug.state import reset_session_runtime, update_session

    target = init_project(tmp_path)
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

    target = init_project(tmp_path)
    write_session(target, url="http://localhost:2550", alias="DefAlias", session_id="sid-d")
    posts: list[str] = []

    def transport(url: str, data: bytes, headers: dict[str, str], timeout: float) -> HttpResponse:
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


def test_background_ping_ensure_and_stop(tmp_path: Path) -> None:
    target = init_project(tmp_path)
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
    target = init_project(tmp_path)
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
    persist_stop(target, stop)

    def factory(client: Any, **kwargs: Any) -> MagicMock:
        return fake_session(clear_cached_stop=MagicMock(), last_stop=stop, _last_stop=stop)

    waited = run_wait(target, timeout=1.0, session_factory=factory)
    assert waited.status == "ok"
    assert waited.ping_running is True
    assert waited.ping_pid is not None


def test_ping_worker_persists_last_stop(tmp_path: Path) -> None:
    from core.debug.ping_worker import persist_stop_from_ping_body

    target = init_project(tmp_path)
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
    target = init_project(tmp_path)
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

    target = init_project(tmp_path)
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

    def transport(url: str, data: bytes, headers: dict[str, str], timeout: float) -> HttpResponse:
        text = data.decode("utf-8")
        marker = "<calc:expressionResultID>"
        rid = text.split(marker)[1].split("</")[0]
        write_eval_result(target, rid, late.format(rid=rid))  # daemon side
        return HttpResponse(status=200, body="<response/>")  # empty POST body

    result = run_evaluate(target, expression="Результат", transport=transport)
    assert result.status == "ok"
    assert result.eval_state == "correctly"
    assert result.result == "84"
