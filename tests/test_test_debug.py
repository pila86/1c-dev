"""Unit tests for test.run --debug / test.wait (#147)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from adapters.test_yaxunit import SpawnedUnitTests
from core.debug.result import DebugResult
from core.exit_codes import PROJECT_ERROR, SUCCESS
from core.test import run_tests, wait_tests
from core.test.constants import CODE_DEBUG_BP, CODE_NO_RUN_META
from core.test.runner_ensure import RunnerEnsureResult
from core.test.store import load_run_meta, run_meta_path, save_run_meta, work_dir
from tests.helpers_project import bootstrap_configuration_project
from tests.test_core_test import _bootstrap_test_project, _ensure_ib, _fake_discovery


@pytest.fixture(autouse=True)
def _stub_runner_ensure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "core.test.ops.ensure_yaxunit_runner",
        lambda **_kwargs: RunnerEnsureResult(status="ok", reason="stub"),
    )


def test_run_bp_requires_debug(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = _bootstrap_test_project(tmp_path)
    _ensure_ib(target)
    onecv8 = tmp_path / "1cv8"
    onecv8.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        "core.test.ops.discover_environment",
        lambda: _fake_discovery(onecv8=onecv8),
    )
    result = run_tests(
        target,
        breakpoints=["src/cfe/test_ext1/CommonModules/ОМ_Арифметика/Ext/Module.bsl:5"],
    )
    assert result.status == "failed"
    assert result.exit_code == PROJECT_ERROR
    assert any(d.get("code") == CODE_DEBUG_BP for d in result.diagnostics)


def test_run_debug_detach_writes_meta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _bootstrap_test_project(tmp_path)
    _ensure_ib(target)
    onecv8 = tmp_path / "1cv8"
    onecv8.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        "core.test.ops.discover_environment",
        lambda: _fake_discovery(onecv8=onecv8),
    )

    def fake_ensure(*_a: Any, **_k: Any) -> DebugResult:
        return DebugResult(
            status="ok",
            url="http://127.0.0.1:1550/",
            debugger_url="http://127.0.0.1:1550/",
            session_id="sess-1",
            breakpoints=[{"file": "Module.bsl", "line": 5}],
        )

    def fake_prepare(*_a: Any, **_k: Any) -> DebugResult:
        return DebugResult(status="ok")

    def fake_arm(*_a: Any, **_k: Any) -> DebugResult:
        return DebugResult(status="ok")

    def fake_spawn(onecv8_path: Path, **kwargs: Any) -> SpawnedUnitTests:
        wd = Path(kwargs["work_dir"])
        wd.mkdir(parents=True, exist_ok=True)
        return SpawnedUnitTests(
            pid=4242,
            argv=(str(onecv8_path), "ENTERPRISE", "/Debug"),
            work_dir=wd,
            report_path=wd / "junit.xml",
            exit_code_path=wd / "exit-code.txt",
            log_path=wd / "yaxunit.log",
            out_log_path=wd / "out.log",
            config_path=wd / "cfg.json",
        )

    monkeypatch.setattr("core.debug.ops.ensure_debug_for_runtime", fake_ensure)
    monkeypatch.setattr("core.debug.ops.prepare_debug_for_spawn", fake_prepare)
    monkeypatch.setattr("core.debug.ops.await_debug_targets_armed", fake_arm)

    result = run_tests(
        target,
        debug=True,
        breakpoints=["src/cfe/test_ext1/CommonModules/ОМ_Арифметика/Ext/Module.bsl:5"],
        spawn_unit_tests_fn=fake_spawn,
    )
    assert result.status == "running", result.to_payload()
    assert result.exit_code == SUCCESS
    assert result.pid == 4242
    assert result.debug_enabled is True
    assert result.debugger_url == "http://127.0.0.1:1550/"
    meta, diags = load_run_meta(target)
    assert meta is not None, diags
    assert meta["pid"] == 4242
    assert meta["debug"] is True


def test_wait_tests_collects_junit(tmp_path: Path) -> None:
    target = _bootstrap_test_project(tmp_path)
    wd = work_dir(target)
    wd.mkdir(parents=True, exist_ok=True)
    report = wd / "junit.xml"
    report.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<testsuites>
  <testsuite name="Demo" tests="1" failures="0" errors="0" skipped="0" time="0.1">
    <testcase classname="DemoTests" name="Ok" time="0.1"/>
  </testsuite>
</testsuites>
""",
        encoding="utf-8",
    )
    (wd / "exit-code.txt").write_text("0\n", encoding="utf-8")
    (wd / "yaxunit.log").write_text("", encoding="utf-8")
    (wd / "out.log").write_text("", encoding="utf-8")
    save_run_meta(
        target,
        {
            "pid": 9999,
            "workDir": str(wd),
            "reportPath": str(report),
            "exitCodePath": str(wd / "exit-code.txt"),
            "logPath": str(wd / "yaxunit.log"),
            "outLogPath": str(wd / "out.log"),
            "configPath": str(wd / "cfg.json"),
            "argv": ["1cv8"],
            "debug": True,
            "suiteIds": ["unit"],
            "configId": "main",
            "runtimeId": "main",
        },
    )

    result = wait_tests(target, timeout=1.0, is_alive=lambda _pid: False)
    assert result.status == "passed", result.to_payload()
    assert result.exit_code == SUCCESS
    assert result.total == 1
    assert not run_meta_path(target).exists()


def test_wait_without_meta(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert bootstrap_configuration_project(target, name="Shop").status == "ok"
    result = wait_tests(target, timeout=0.1, is_alive=lambda _pid: False)
    assert result.status == "failed"
    assert any(d.get("code") == CODE_NO_RUN_META for d in result.diagnostics)


def test_cli_test_run_debug_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from cli.main import app
    from core.test.result import TestResult as ApiTestResult

    captured: dict[str, Any] = {}

    def fake_run(start: Path | None = None, **kwargs: Any) -> ApiTestResult:
        captured.update(kwargs)
        captured["start"] = start
        return ApiTestResult(
            status="running",
            exit_code=SUCCESS,
            pid=1,
            debug_enabled=True,
        )

    monkeypatch.setattr("cli.test.run_tests", fake_run)
    cli = CliRunner()
    result = cli.invoke(
        app,
        [
            "test",
            "run",
            "--debug",
            "--bp",
            "src/x.bsl:3",
            "--output",
            "json",
        ],
    )
    assert result.exit_code == SUCCESS, result.stdout
    assert captured.get("debug") is True
    assert captured.get("breakpoints") == ["src/x.bsl:3"]
    payload = json.loads(result.stdout)
    assert payload["status"] == "running"


def test_cli_test_wait_help() -> None:
    from typer.testing import CliRunner

    from cli.main import app

    cli = CliRunner()
    result = cli.invoke(app, ["test", "--help"])
    assert result.exit_code == 0
    assert "wait" in result.stdout
