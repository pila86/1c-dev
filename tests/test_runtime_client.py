"""Tests for runtime.start / stop / status (ADR-019)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from adapters.platform.discovery import DiscoveryResult, PlatformInfo, ToolInfo
from adapters.platform_1cv8.constants import CLIENT_META_REL, CLIENT_PID_REL
from adapters.platform_1cv8.process import build_enterprise_argv, is_running, terminate
from adapters.platform_ibcmd.constants import IB_MARKER
from cli.main import app
from core.exit_codes import ENV_UNAVAILABLE, PROJECT_ERROR, RUNTIME_FAILURE, SUCCESS
from core.project import init_project
from core.runtime import (
    CODE_CLIENT_FAILED,
    CODE_IB_MISSING,
    CODE_ONECV8_MISSING,
    CODE_PROJECT,
    run_start,
    run_status,
    run_stop,
)
from core.runtime.state import clear_state, read_meta, read_pid, write_state

runner = CliRunner()


def _fake_discovery(*, onecv8: Path | None) -> DiscoveryResult:
    return DiscoveryResult(
        platform=PlatformInfo(found=True, version="8.3.25.1560", path=Path("/opt/1cv8")),
        ibcmd=ToolInfo(found=True, path=Path("/fake/ibcmd")),
        onecv8=ToolInfo(found=onecv8 is not None, path=onecv8),
    )


def _init_with_ib(tmp_path: Path) -> Path:
    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(target, project_type="configuration", name="Shop").status == "ok"
    ib = target / ".runtime" / "ib"
    ib.mkdir(parents=True, exist_ok=True)
    (ib / IB_MARKER).write_bytes(b"")
    return target


def test_build_enterprise_argv_with_debug(tmp_path: Path) -> None:
    onecv8 = tmp_path / "1cv8"
    ib = tmp_path / "ib"
    ib.mkdir()
    argv = build_enterprise_argv(onecv8, ib_path=ib, debug=True)
    assert argv[0] == str(onecv8)
    assert argv[1] == "ENTERPRISE"
    assert argv[2].startswith("/F")
    assert Path(argv[2][2:]) == ib.resolve()
    assert "/Debug" in argv


def test_run_start_no_project(tmp_path: Path) -> None:
    result = run_start(
        tmp_path,
        discover=lambda: _fake_discovery(onecv8=Path("/fake/1cv8")),
        settle_seconds=0,
    )
    assert result.status == "failed"
    assert any(d.get("code") == CODE_PROJECT for d in result.diagnostics)


def test_run_start_missing_ib(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(target, project_type="configuration", name="Shop").status == "ok"
    result = run_start(
        target,
        discover=lambda: _fake_discovery(onecv8=Path("/fake/1cv8")),
        settle_seconds=0,
    )
    assert result.status == "failed"
    assert any(d.get("code") == CODE_IB_MISSING for d in result.diagnostics)


def test_run_start_missing_onecv8(tmp_path: Path) -> None:
    target = _init_with_ib(tmp_path)
    result = run_start(
        target,
        discover=lambda: _fake_discovery(onecv8=None),
        settle_seconds=0,
    )
    assert result.status == "failed"
    assert any(d.get("code") == CODE_ONECV8_MISSING for d in result.diagnostics)


def test_run_start_stop_status_happy(tmp_path: Path) -> None:
    target = _init_with_ib(tmp_path)
    alive: dict[int, bool] = {}
    spawned: list[list[str]] = []

    def spawn(argv: list[str]) -> int:
        spawned.append(list(argv))
        pid = 4242
        alive[pid] = True
        return pid

    def terminate_fn(pid: int) -> bool:
        alive[pid] = False
        return True

    result = run_start(
        target,
        debug=True,
        discover=lambda: _fake_discovery(onecv8=Path("/fake/1cv8")),
        spawn=spawn,
        is_alive=lambda pid: alive.get(pid, False),
        settle_seconds=0,
    )
    assert result.status == "ok"
    assert result.running is True
    assert result.pid == 4242
    assert result.debug_enabled is True
    assert result.mode == "enterprise"
    assert "/Debug" in spawned[0]
    assert read_pid(target) == 4242
    assert read_meta(target)["debug"]["enabled"] is True

    again = run_start(
        target,
        debug=False,
        discover=lambda: _fake_discovery(onecv8=Path("/fake/1cv8")),
        spawn=spawn,
        is_alive=lambda pid: alive.get(pid, False),
        settle_seconds=0,
    )
    assert again.status == "ok"
    assert again.pid == 4242
    assert len(spawned) == 1

    status = run_status(target, is_alive=lambda pid: alive.get(pid, False))
    assert status.running is True
    assert status.debug_enabled is True

    stop = run_stop(
        target,
        is_alive=lambda pid: alive.get(pid, False),
        terminate_fn=terminate_fn,
    )
    assert stop.status == "ok"
    assert stop.running is False
    assert read_pid(target) is None

    status2 = run_status(target, is_alive=lambda pid: alive.get(pid, False))
    assert status2.running is False


def test_run_start_immediate_exit(tmp_path: Path) -> None:
    target = _init_with_ib(tmp_path)

    result = run_start(
        target,
        discover=lambda: _fake_discovery(onecv8=Path("/fake/1cv8")),
        spawn=lambda _argv: 99,
        is_alive=lambda _pid: False,
        settle_seconds=0,
    )
    assert result.status == "failed"
    assert any(d.get("code") == CODE_CLIENT_FAILED for d in result.diagnostics)


def test_stale_pid_cleared_on_status(tmp_path: Path) -> None:
    target = _init_with_ib(tmp_path)
    write_state(target, pid=777, debug=True)
    status = run_status(target, is_alive=lambda _pid: False)
    assert status.running is False
    assert read_pid(target) is None


def test_cli_runtime_start_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = _init_with_ib(tmp_path)
    monkeypatch.chdir(target)

    def fake_start(start: Path | None = None, **kwargs: object):
        from core.runtime.result import RuntimeResult

        return RuntimeResult(
            status="ok",
            root=target,
            runtime_path=target / ".runtime" / "ib",
            running=True,
            pid=111,
            mode="enterprise",
            debug_enabled=True,
        )

    monkeypatch.setattr("cli.runtime.run_start", fake_start)
    result = runner.invoke(app, ["runtime", "start", "--debug", "--output", "json"])
    assert result.exit_code == SUCCESS, result.output
    payload = json.loads(result.stdout)
    assert payload["running"] is True
    assert payload["pid"] == 111
    assert payload["debug"]["enabled"] is True


def test_cli_runtime_start_missing_ib_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(target, project_type="configuration", name="Shop").status == "ok"
    monkeypatch.chdir(target)
    monkeypatch.setattr(
        "core.runtime.run.discover_environment",
        lambda: _fake_discovery(onecv8=Path("/fake/1cv8")),
    )
    result = runner.invoke(app, ["runtime", "start", "--output", "json"])
    assert result.exit_code == PROJECT_ERROR
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert any(d.get("code") == CODE_IB_MISSING for d in payload["diagnostics"])


def test_cli_exit_onecv8_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = _init_with_ib(tmp_path)
    monkeypatch.chdir(target)
    monkeypatch.setattr(
        "core.runtime.run.discover_environment",
        lambda: _fake_discovery(onecv8=None),
    )
    result = runner.invoke(app, ["runtime", "start", "--output", "json"])
    assert result.exit_code == ENV_UNAVAILABLE


def test_cli_exit_client_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = _init_with_ib(tmp_path)
    monkeypatch.chdir(target)
    monkeypatch.setattr(
        "core.runtime.run.discover_environment",
        lambda: _fake_discovery(onecv8=Path("/fake/1cv8")),
    )

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr("core.runtime.run.start_enterprise_client", boom)
    result = runner.invoke(app, ["runtime", "start", "--output", "json"])
    assert result.exit_code == RUNTIME_FAILURE


def test_is_running_and_terminate_posix(monkeypatch: pytest.MonkeyPatch) -> None:
    import adapters.platform_1cv8.process as proc

    monkeypatch.setattr(proc.sys, "platform", "linux")

    def fake_kill(pid: int, sig: int) -> None:
        if sig == 0 and pid == 1:
            return
        if pid == 2:
            raise ProcessLookupError()
        raise ProcessLookupError()

    monkeypatch.setattr(proc.os, "kill", fake_kill)
    assert is_running(1) is True
    assert is_running(2) is False

    state = {"alive": True}

    def kill2(pid: int, sig: int) -> None:
        if sig == 0:
            if not state["alive"]:
                raise ProcessLookupError()
            return
        state["alive"] = False

    monkeypatch.setattr(proc.os, "kill", kill2)
    assert terminate(5, timeout=0.2) is True


def test_win_process_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    import adapters.platform_1cv8.process as proc

    monkeypatch.setattr(proc.sys, "platform", "win32")

    class FakeKernel:
        def __init__(self) -> None:
            self.handles: list[int] = []
            self.open_results: list[int] = [42]

        def OpenProcess(self, *_a: object, **_k: object) -> int:
            if self.open_results:
                return self.open_results.pop(0)
            return 0

        def CloseHandle(self, handle: int) -> None:
            self.handles.append(handle)

        def TerminateProcess(self, *_a: object, **_k: object) -> int:
            return 1

        def WaitForSingleObject(self, *_a: object, **_k: object) -> int:
            return 0

    kernel = FakeKernel()
    fake_ctypes = SimpleNamespace(windll=SimpleNamespace(kernel32=kernel))
    monkeypatch.setitem(__import__("sys").modules, "ctypes", fake_ctypes)

    assert proc._win_is_running(10) is True
    assert 42 in kernel.handles

    kernel.open_results = [7, 0]
    assert proc._win_terminate(10, timeout=0.1) is True


def test_clear_state(tmp_path: Path) -> None:
    write_state(tmp_path, pid=1, debug=False)
    assert (tmp_path / CLIENT_PID_REL).is_file()
    assert (tmp_path / CLIENT_META_REL).is_file()
    clear_state(tmp_path)
    assert not (tmp_path / CLIENT_PID_REL).exists()
