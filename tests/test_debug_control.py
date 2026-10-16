"""core.debug: wait / continue / step / pause (mocks)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from adapters.debug_http import (
    CODE_WAIT_TIMEOUT,
    PROPERTY_ID_COMMON_MODULE,
    HttpResponse,
    StackFrame,
    StopEvent,
)
from core.debug import (
    run_continue,
    run_pause,
    run_stack,
    run_step_in,
    run_step_out,
    run_step_over,
    run_wait,
)
from core.debug.state import (
    read_session,
    serialize_last_stop,
    write_session,
)
from core.exit_codes import RUNTIME_FAILURE
from tests.helpers_debug import (
    SPIKE_OBJECT,
    SPIKE_TARGET,
    fake_session,
    init_project,
    persist_stop,
)

pytestmark = pytest.mark.usefixtures("stub_background_ping")


def test_wait_timeout_exit_4(tmp_path: Path) -> None:
    target = init_project(tmp_path)
    write_session(target, url="http://localhost:2550", alias="DefAlias", session_id="sid-1")

    def factory(client: Any, **kwargs: Any) -> MagicMock:
        return fake_session(clear_cached_stop=MagicMock())

    result = run_wait(target, timeout=0.1, session_factory=factory)
    assert result.status == "failed"
    assert result.exit_code == RUNTIME_FAILURE
    assert any(d.get("code") == CODE_WAIT_TIMEOUT for d in result.diagnostics)


def test_wait_returns_immediately_when_already_stopped(tmp_path: Path) -> None:
    target = init_project(tmp_path)
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

    target = init_project(tmp_path)
    write_session(target, url="http://localhost:2550", alias="DefAlias", session_id="sid-x")
    t0 = time.perf_counter()
    result = run_wait(target, timeout=30.0, client_alive=lambda: False)
    assert time.perf_counter() - t0 < 5
    assert result.status == "failed"
    assert any(d.get("code") == CODE_CLIENT_EXITED for d in result.diagnostics)


def test_wait_times_out_when_client_alive_without_stop(tmp_path: Path) -> None:
    target = init_project(tmp_path)
    write_session(target, url="http://localhost:2550", alias="DefAlias", session_id="sid-t")
    result = run_wait(target, timeout=0.2, client_alive=lambda: True)
    assert result.status == "failed"
    assert any(d.get("code") == CODE_WAIT_TIMEOUT for d in result.diagnostics)


def test_wait_fresh_drops_recorded_stop(tmp_path: Path) -> None:
    target = init_project(tmp_path)
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
    target = init_project(tmp_path)
    write_session(target, url="http://localhost:2550", alias="DefAlias", session_id="sid-e")

    def experimental(result: Any) -> bool:
        return any(
            "экспериментал" in str(d.get("message"))
            for d in result.diagnostics
            if d.get("severity") == "warning"
        )

    for run in (run_step_in, run_step_over, run_step_out, run_continue):
        result = run(target, wait=False, session_factory=lambda c, **k: fake_session())
        assert result.status == "ok", run.__name__
        assert not experimental(result), run.__name__
    paused = run_pause(target, wait=False, session_factory=lambda c, **k: fake_session())
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

    target = init_project(tmp_path)
    write_session(target, url="http://localhost:2550", alias="DefAlias", session_id="sid-fin")
    result = run(
        target,
        timeout=5.0,
        client_alive=lambda: False,
        session_factory=lambda c, **k: fake_session(),
    )
    assert result.status == "ok", result.to_payload()
    assert not result.call_stack
    exited = [d for d in result.diagnostics if d.get("code") == CODE_CLIENT_EXITED]
    assert exited
    assert label in str(exited[0].get("message"))
    assert "lastStop" not in (read_session(target) or {})


def test_pause_fails_when_client_exited(tmp_path: Path) -> None:
    from core.debug.constants import CODE_CLIENT_EXITED

    target = init_project(tmp_path)
    write_session(target, url="http://localhost:2550", alias="DefAlias", session_id="sid-p")
    result = run_pause(
        target,
        timeout=5.0,
        client_alive=lambda: False,
        session_factory=lambda c, **k: fake_session(),
    )
    assert result.status == "failed"
    assert any(d.get("code") == CODE_CLIENT_EXITED for d in result.diagnostics)


def test_wait_persists_last_stop_for_next_cli_process(tmp_path: Path) -> None:
    """Short-lived CLI: wait picks up lastStop; stack/continue restore from disk."""
    target = init_project(tmp_path)
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
        sess = fake_session(clear_cached_stop=MagicMock())
        sess.session_id = kwargs.get("session_id", "sid-persist")
        return sess

    waited = run_wait(target, timeout=1.0, session_factory=factory, client_alive=lambda: True)
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
    target = init_project(tmp_path)
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
            persist_stop(target, stop),
            "ok",
        )[-1]
    )

    def factory(client: Any, **kwargs: Any) -> MagicMock:
        return fake_session(
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
    target = init_project(tmp_path)
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
    step_over = MagicMock(side_effect=lambda *a, **k: (persist_stop(target, after), "ok")[-1])

    def factory(client: Any, **kwargs: Any) -> MagicMock:
        return fake_session(
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
    target = init_project(tmp_path)
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
    step_in = MagicMock(side_effect=lambda *a, **k: (persist_stop(target, after_stop), "ok")[-1])

    def factory(client: Any, **kwargs: Any) -> MagicMock:
        return fake_session(
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
