"""Tests for ibcmd check (ADR-009)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from adapters.platform.discovery import DiscoveryResult, PlatformInfo, ToolInfo
from adapters.platform_ibcmd.client import IbcmdRunResult
from adapters.platform_ibcmd.constants import (
    CODE_CHECK_FAILED,
    CODE_CHECK_IBCMD_MISSING,
    CODE_CHECK_IB_MISSING,
    CODE_CHECK_PROJECT,
    IB_MARKER,
)
from cli.main import app
from core.build import run_build
from core.check import run_check
from core.exit_codes import CHECK_FAILURE, ENV_UNAVAILABLE, PROJECT_ERROR, SUCCESS
from core.project import init_project

runner = CliRunner()
SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"


def _fake_discovery(*, ibcmd: Path | None) -> DiscoveryResult:
    return DiscoveryResult(
        platform=PlatformInfo(found=True, version="8.3.25.1560", path=Path("/opt/1cv8")),
        ibcmd=ToolInfo(found=ibcmd is not None, path=ibcmd),
        onecv8=ToolInfo(found=False, path=None),
    )


def _ok_run(argv: list[str]) -> IbcmdRunResult:
    if "create" in argv:
        db_path = None
        for arg in argv:
            if arg.startswith("--db-path="):
                db_path = Path(arg.split("=", 1)[1])
        if db_path is not None:
            db_path.mkdir(parents=True, exist_ok=True)
            (db_path / IB_MARKER).write_bytes(b"")
    return IbcmdRunResult(returncode=0, stdout="ok", stderr="", argv=argv)


def _fail_check_run(argv: list[str]) -> IbcmdRunResult:
    return IbcmdRunResult(
        returncode=1,
        stdout="",
        stderr="Синтаксическая ошибка BSL: ожидался символ ';'",
        argv=argv,
    )


def _ensure_ib(target: Path) -> None:
    ib_dir = target / ".runtime" / "ib"
    ib_dir.mkdir(parents=True, exist_ok=True)
    (ib_dir / IB_MARKER).write_bytes(b"")


def test_run_check_no_project(tmp_path: Path) -> None:
    result = run_check(tmp_path, discover=lambda: _fake_discovery(ibcmd=Path("/fake/ibcmd")))
    assert result.status == "failed"
    assert any(d.get("code") == CODE_CHECK_PROJECT for d in result.diagnostics)


def test_run_check_missing_ibcmd(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(target, project_type="configuration", name="Shop").status == "ok"
    _ensure_ib(target)
    result = run_check(target, discover=lambda: _fake_discovery(ibcmd=None))
    assert result.status == "failed"
    assert any(d.get("code") == CODE_CHECK_IBCMD_MISSING for d in result.diagnostics)


def test_run_check_missing_ib(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(target, project_type="configuration", name="Shop").status == "ok"
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    result = run_check(target, discover=lambda: _fake_discovery(ibcmd=ibcmd), run=_ok_run)
    assert result.status == "failed"
    assert any(d.get("code") == CODE_CHECK_IB_MISSING for d in result.diagnostics)
    assert any("build" in (d.get("suggestion") or "") for d in result.diagnostics)


def test_run_check_happy_mock(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(target, project_type="configuration", name="Shop").status == "ok"
    _ensure_ib(target)
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("#!/bin/sh\n", encoding="utf-8")

    result = run_check(
        target,
        discover=lambda: _fake_discovery(ibcmd=ibcmd),
        run=_ok_run,
    )
    assert result.status == "ok"
    payload = result.to_payload()
    assert payload["status"] == "ok"
    assert payload["runtimePath"] == ".runtime/ib"
    assert "duration" in payload


def test_run_check_bsl_failure(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(target, project_type="configuration", name="Shop").status == "ok"
    _ensure_ib(target)
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")

    result = run_check(
        target,
        discover=lambda: _fake_discovery(ibcmd=ibcmd),
        run=_fail_check_run,
    )
    assert result.status == "failed"
    assert any(d.get("code") == CODE_CHECK_FAILED for d in result.diagnostics)
    assert any(d.get("source") == "platform" for d in result.diagnostics)
    assert any("синтаксическая" in d.get("message", "").lower() for d in result.diagnostics)


def test_check_payload_matches_schema(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(target, project_type="configuration", name="Shop").status == "ok"
    _ensure_ib(target)
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    result = run_check(
        target,
        discover=lambda: _fake_discovery(ibcmd=ibcmd),
        run=_ok_run,
    )
    schema = json.loads((SCHEMAS / "check.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    diag = json.loads((SCHEMAS / "diagnostics.schema.json").read_text(encoding="utf-8"))
    schema["properties"]["diagnostics"]["items"] = diag
    Draft202012Validator(schema).validate(result.to_payload())


def test_cli_check_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(target, project_type="configuration", name="Shop").status == "ok"
    _ensure_ib(target)
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    monkeypatch.chdir(target)

    def fake_discover() -> DiscoveryResult:
        return _fake_discovery(ibcmd=ibcmd)

    monkeypatch.setattr("core.check.run.discover_environment", fake_discover)
    monkeypatch.setattr("core.check.run.check_config", _fake_check_ok)

    result = runner.invoke(app, ["check", "--output", "json"])
    assert result.exit_code == SUCCESS
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"


def test_cli_check_platform_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(target, project_type="configuration", name="Shop").status == "ok"
    _ensure_ib(target)
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    monkeypatch.chdir(target)
    monkeypatch.setattr(
        "core.check.run.discover_environment",
        lambda: _fake_discovery(ibcmd=ibcmd),
    )
    monkeypatch.setattr("core.check.run.check_config", _fake_check_ok)
    result = runner.invoke(app, ["check", "--platform", "--output", "json"])
    assert result.exit_code == SUCCESS


def _fake_check_ok(*_args: Any, **_kwargs: Any) -> IbcmdRunResult:
    return IbcmdRunResult(returncode=0, stdout="ok", stderr="", argv=["ibcmd", "check"])


def test_cli_check_missing_ibcmd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(target, project_type="configuration", name="Shop").status == "ok"
    _ensure_ib(target)
    monkeypatch.chdir(target)
    monkeypatch.setattr(
        "core.check.run.discover_environment",
        lambda: _fake_discovery(ibcmd=None),
    )
    result = runner.invoke(app, ["check", "--output", "json"])
    assert result.exit_code == ENV_UNAVAILABLE
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"


def test_cli_check_failure_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(target, project_type="configuration", name="Shop").status == "ok"
    _ensure_ib(target)
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    monkeypatch.chdir(target)
    monkeypatch.setattr(
        "core.check.run.discover_environment",
        lambda: _fake_discovery(ibcmd=ibcmd),
    )
    monkeypatch.setattr("core.check.run.check_config", _fake_check_fail)
    result = runner.invoke(app, ["check", "--output", "json"])
    assert result.exit_code == CHECK_FAILURE


def _fake_check_fail(*_args: Any, **_kwargs: Any) -> IbcmdRunResult:
    from adapters.platform_ibcmd import IbcmdError
    from core.diagnostics import error

    raise IbcmdError(
        "boom",
        code=CODE_CHECK_FAILED,
        diagnostics=[error("синтаксическая ошибка", code=CODE_CHECK_FAILED, source="platform")],
        step="check",
    )


def test_cli_check_no_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["check", "--output", "json"])
    assert result.exit_code == PROJECT_ERROR


def test_cli_check_missing_ib_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(target, project_type="configuration", name="Shop").status == "ok"
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    monkeypatch.chdir(target)
    monkeypatch.setattr(
        "core.check.run.discover_environment",
        lambda: _fake_discovery(ibcmd=ibcmd),
    )
    result = runner.invoke(app, ["check", "--output", "json"])
    assert result.exit_code == PROJECT_ERROR


@pytest.mark.integration
def test_integration_ibcmd_check(tmp_path: Path) -> None:
    """Real ibcmd build then check; skip if platform unavailable."""
    from adapters.platform import discover_environment

    discovery = discover_environment()
    if not discovery.ibcmd.found or discovery.ibcmd.path is None:
        pytest.skip("ibcmd не найден — integration check пропущен")

    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(target, project_type="configuration", name="Shop").status == "ok"

    build = run_build(target)
    assert build.status == "ok", build.to_payload()

    result = run_check(target)
    assert result.status == "ok", result.to_payload()
    assert (target / ".runtime" / "ib" / IB_MARKER).is_file()
