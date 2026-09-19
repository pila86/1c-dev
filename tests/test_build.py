"""Tests for ibcmd build (ADR-008)."""

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
    CODE_IBCMD_FAILED,
    CODE_IBCMD_MISSING,
    CODE_PROJECT,
    IB_MARKER,
)
from cli.main import app
from core.build import run_build
from core.exit_codes import BUILD_FAILURE, ENV_UNAVAILABLE, PROJECT_ERROR, SUCCESS
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
    # Simulate create writing IB marker when create is invoked
    if "create" in argv:
        db_path = None
        for arg in argv:
            if arg.startswith("--db-path="):
                db_path = Path(arg.split("=", 1)[1])
        if db_path is not None:
            db_path.mkdir(parents=True, exist_ok=True)
            (db_path / IB_MARKER).write_bytes(b"")
    if "save" in argv:
        # last path-like arg after --db is the cf path? argv: ... --db /path.cf
        try:
            idx = argv.index("--db")
            cf = Path(argv[idx + 1])
            cf.parent.mkdir(parents=True, exist_ok=True)
            cf.write_bytes(b"CF")
        except (ValueError, IndexError):
            pass
    return IbcmdRunResult(returncode=0, stdout="ok", stderr="", argv=argv)


def _fail_run(argv: list[str]) -> IbcmdRunResult:
    return IbcmdRunResult(
        returncode=1,
        stdout="",
        stderr="simulated ibcmd failure",
        argv=argv,
    )


def test_run_build_no_project(tmp_path: Path) -> None:
    result = run_build(tmp_path, discover=lambda: _fake_discovery(ibcmd=Path("/fake/ibcmd")))
    assert result.status == "failed"
    assert any(d.get("code") == CODE_PROJECT for d in result.diagnostics)


def test_run_build_missing_ibcmd(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(target, project_type="configuration", name="Shop").status == "ok"
    result = run_build(target, discover=lambda: _fake_discovery(ibcmd=None))
    assert result.status == "failed"
    assert any(d.get("code") == CODE_IBCMD_MISSING for d in result.diagnostics)


def test_run_build_happy_mock(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(target, project_type="configuration", name="Shop").status == "ok"
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("#!/bin/sh\n", encoding="utf-8")

    result = run_build(
        target,
        discover=lambda: _fake_discovery(ibcmd=ibcmd),
        run=_ok_run,
    )
    assert result.status == "ok"
    assert result.steps == ["create", "import", "apply"]
    assert (target / ".runtime" / "ib" / IB_MARKER).is_file()
    payload = result.to_payload()
    assert payload["status"] == "ok"
    assert payload["runtimePath"] == ".runtime/ib"
    assert "duration" in payload


def test_run_build_skips_create_when_ib_exists(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(target, project_type="configuration", name="Shop").status == "ok"
    ib_dir = target / ".runtime" / "ib"
    ib_dir.mkdir(parents=True, exist_ok=True)
    (ib_dir / IB_MARKER).write_bytes(b"")
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")

    result = run_build(
        target,
        discover=lambda: _fake_discovery(ibcmd=ibcmd),
        run=_ok_run,
    )
    assert result.status == "ok"
    assert result.steps == ["import", "apply"]


def test_run_build_artifact_cf(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(target, project_type="configuration", name="Shop").status == "ok"
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")

    result = run_build(
        target,
        artifact="cf",
        discover=lambda: _fake_discovery(ibcmd=ibcmd),
        run=_ok_run,
    )
    assert result.status == "ok"
    assert result.steps == ["create", "import", "apply", "save"]
    assert result.artifact == "build/out/configuration.cf"
    assert (target / "build" / "out" / "configuration.cf").is_file()


def test_run_build_ibcmd_failure(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(target, project_type="configuration", name="Shop").status == "ok"
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")

    result = run_build(
        target,
        discover=lambda: _fake_discovery(ibcmd=ibcmd),
        run=_fail_run,
    )
    assert result.status == "failed"
    assert any(d.get("code") == CODE_IBCMD_FAILED for d in result.diagnostics)
    assert any(d.get("source") == "platform" for d in result.diagnostics)


def test_run_build_invalid_artifact(tmp_path: Path) -> None:
    result = run_build(tmp_path, artifact="epf")
    assert result.status == "failed"
    assert any(d.get("code") == "1CB006" for d in result.diagnostics)


def test_build_payload_matches_schema(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(target, project_type="configuration", name="Shop").status == "ok"
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    result = run_build(
        target,
        discover=lambda: _fake_discovery(ibcmd=ibcmd),
        run=_ok_run,
    )
    schema = json.loads((SCHEMAS / "build.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    # Resolve $ref to diagnostics locally
    diag = json.loads((SCHEMAS / "diagnostics.schema.json").read_text(encoding="utf-8"))
    schema["properties"]["diagnostics"]["items"] = diag
    Draft202012Validator(schema).validate(result.to_payload())


def test_cli_build_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(target, project_type="configuration", name="Shop").status == "ok"
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")

    monkeypatch.chdir(target)

    def fake_discover() -> DiscoveryResult:
        return _fake_discovery(ibcmd=ibcmd)

    monkeypatch.setattr("core.build.run.discover_environment", fake_discover)
    monkeypatch.setattr("core.build.run.build_with_ibcmd", _fake_build_ok)

    result = runner.invoke(app, ["build", "--output", "json"])
    assert result.exit_code == SUCCESS
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert "import" in payload["steps"]


def _fake_build_ok(
    ibcmd: Path,
    *,
    db_path: Path,
    data_path: Path,
    source_dir: Path,
    cf_path: Path | None = None,
    run: Any = None,
) -> list[str]:
    db_path.mkdir(parents=True, exist_ok=True)
    (db_path / IB_MARKER).write_bytes(b"")
    steps = ["create", "import", "apply"]
    if cf_path is not None:
        cf_path.parent.mkdir(parents=True, exist_ok=True)
        cf_path.write_bytes(b"CF")
        steps.append("save")
    return steps


def test_cli_build_missing_ibcmd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(target, project_type="configuration", name="Shop").status == "ok"
    monkeypatch.chdir(target)
    monkeypatch.setattr(
        "core.build.run.discover_environment",
        lambda: _fake_discovery(ibcmd=None),
    )
    result = runner.invoke(app, ["build", "--output", "json"])
    assert result.exit_code == ENV_UNAVAILABLE
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"


def test_cli_build_failure_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(target, project_type="configuration", name="Shop").status == "ok"
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    monkeypatch.chdir(target)
    monkeypatch.setattr(
        "core.build.run.discover_environment",
        lambda: _fake_discovery(ibcmd=ibcmd),
    )
    monkeypatch.setattr("core.build.run.build_with_ibcmd", _fake_build_fail)
    result = runner.invoke(app, ["build", "--output", "json"])
    assert result.exit_code == BUILD_FAILURE


def _fake_build_fail(*_args: Any, **_kwargs: Any) -> list[str]:
    from adapters.platform_ibcmd import IbcmdError
    from core.diagnostics import error

    raise IbcmdError(
        "boom",
        diagnostics=[error("boom", code=CODE_IBCMD_FAILED, source="platform")],
        step="import",
    )


def test_cli_build_no_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["build", "--output", "json"])
    assert result.exit_code == PROJECT_ERROR


@pytest.mark.integration
def test_integration_ibcmd_build(tmp_path: Path) -> None:
    """Real ibcmd build; skip if platform unavailable."""
    from adapters.platform import discover_environment

    discovery = discover_environment()
    if not discovery.ibcmd.found or discovery.ibcmd.path is None:
        pytest.skip("ibcmd не найден — integration build пропущен")

    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(target, project_type="configuration", name="Shop").status == "ok"

    result = run_build(target)
    assert result.status == "ok", result.to_payload()
    assert "import" in result.steps
    assert "apply" in result.steps
    assert (target / ".runtime" / "ib" / IB_MARKER).is_file()
