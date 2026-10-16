"""core.debug ↔ core.runtime: runtime start --debug / --bp, stop teardown."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from adapters.debug_http import (
    PROPERTY_ID_COMMON_MODULE,
)
from core.debug import (
    CODE_PROJECT,
    DebugResult,
)
from core.debug.ping import ensure_background_ping
from core.debug.state import (
    read_session,
    write_session,
)
from core.exit_codes import SUCCESS
from core.runtime import run_start
from core.runtime.state import read_meta
from tests.helpers_debug import (
    SPIKE_OBJECT,
    SPIKE_TARGET,
    init_project,
    make_discovery,
)

pytestmark = pytest.mark.usefixtures("stub_background_ping")


def test_runtime_start_debug_http_argv(tmp_path: Path) -> None:
    from adapters.platform_ibcmd.constants import IB_MARKER

    target = init_project(tmp_path)
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
        discover=lambda: make_discovery(dbgs=Path("/fake/dbgs")),
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


def test_runtime_start_bp_requires_debug(tmp_path: Path) -> None:
    target = init_project(tmp_path)
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

    target = init_project(tmp_path)
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
        discover=lambda: make_discovery(dbgs=Path("/fake/dbgs")),
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


def test_runtime_stop_runs_debug_teardown(tmp_path: Path) -> None:
    from core.runtime import run_stop

    target = init_project(tmp_path)
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
