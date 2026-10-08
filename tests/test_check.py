"""Tests for platform check: ibcmd metadata + /CheckModules (ADR-009 / ADR-030)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from adapters.platform.discovery import DiscoveryResult, PlatformInfo, ToolInfo
from adapters.platform_1cv8 import CheckModulesError
from adapters.platform_ibcmd.client import IbcmdRunResult
from adapters.platform_ibcmd.constants import (
    CODE_CHECK_FAILED,
    CODE_CHECK_IB_MISSING,
    CODE_CHECK_IBCMD_MISSING,
    CODE_CHECK_ONECV8_MISSING,
    CODE_CHECK_PROJECT,
    IB_MARKER,
)
from cli.main import app
from core.build import run_build
from core.check import run_check
from core.diagnostics import error
from core.exit_codes import CHECK_FAILURE, ENV_UNAVAILABLE, PROJECT_ERROR, SUCCESS
from core.metadata import catalog_from_parts, create_metadata
from tests.helpers_project import bootstrap_configuration_project

runner = CliRunner()
SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"


def _fake_discovery(
    *,
    ibcmd: Path | None,
    onecv8: Path | None = None,
) -> DiscoveryResult:
    return DiscoveryResult(
        platform=PlatformInfo(found=True, version="8.3.25.1560", path=Path("/opt/1cv8")),
        ibcmd=ToolInfo(found=ibcmd is not None, path=ibcmd),
        onecv8=ToolInfo(found=onecv8 is not None, path=onecv8),
        onecv8c=ToolInfo(found=False, path=None),
        ibsrv=ToolInfo(found=False, path=None),
        webinst=ToolInfo(found=False, path=None),
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
        stderr="метаданные: ошибка",
        argv=argv,
    )


def _ensure_ib(target: Path) -> None:
    ib_dir = target / ".1c-dev" / "runtime" / "main"
    ib_dir.mkdir(parents=True, exist_ok=True)
    (ib_dir / IB_MARKER).write_bytes(b"")


def _fake_modules_ok(*_args: Any, **_kwargs: Any) -> None:
    return None


def _fake_modules_fail(*_args: Any, **_kwargs: Any) -> None:
    from core.diagnostics import Diagnostic

    diag: Diagnostic = {
        "severity": "error",
        "code": CODE_CHECK_FAILED,
        "message": "Ожидается выражение",
        "object": "CommonModule.BrokenServer",
        "module": "Module",
        "line": 2,
        "column": 8,
        "source": "platform",
    }
    raise CheckModulesError(
        "синтаксические ошибки модулей",
        code=CODE_CHECK_FAILED,
        diagnostics=[diag],
    )


def test_run_check_no_project(tmp_path: Path) -> None:
    result = run_check(
        tmp_path,
        discover=lambda: _fake_discovery(
            ibcmd=Path("/fake/ibcmd"),
            onecv8=Path("/fake/1cv8"),
        ),
    )
    assert result.status == "failed"
    assert any(d.get("code") == CODE_CHECK_PROJECT for d in result.diagnostics)


def test_run_check_missing_ibcmd(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert bootstrap_configuration_project(target, name="Shop").status == "ok"
    _ensure_ib(target)
    result = run_check(
        target,
        discover=lambda: _fake_discovery(ibcmd=None, onecv8=Path("/fake/1cv8")),
    )
    assert result.status == "failed"
    assert any(d.get("code") == CODE_CHECK_IBCMD_MISSING for d in result.diagnostics)


def test_run_check_missing_onecv8(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert bootstrap_configuration_project(target, name="Shop").status == "ok"
    _ensure_ib(target)
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    result = run_check(
        target,
        discover=lambda: _fake_discovery(ibcmd=ibcmd, onecv8=None),
        run=_ok_run,
    )
    assert result.status == "failed"
    assert any(d.get("code") == CODE_CHECK_ONECV8_MISSING for d in result.diagnostics)


def test_run_check_missing_ib(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert bootstrap_configuration_project(target, name="Shop").status == "ok"
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    onecv8 = tmp_path / "1cv8"
    onecv8.write_text("", encoding="utf-8")
    result = run_check(
        target,
        discover=lambda: _fake_discovery(ibcmd=ibcmd, onecv8=onecv8),
        run=_ok_run,
        modules_fn=_fake_modules_ok,
    )
    assert result.status == "failed"
    assert any(d.get("code") == CODE_CHECK_IB_MISSING for d in result.diagnostics)
    assert any("build" in (d.get("suggestion") or "") for d in result.diagnostics)


def test_run_check_happy_mock(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert bootstrap_configuration_project(target, name="Shop").status == "ok"
    _ensure_ib(target)
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("#!/bin/sh\n", encoding="utf-8")
    onecv8 = tmp_path / "1cv8"
    onecv8.write_text("", encoding="utf-8")

    result = run_check(
        target,
        discover=lambda: _fake_discovery(ibcmd=ibcmd, onecv8=onecv8),
        run=_ok_run,
        modules_fn=_fake_modules_ok,
    )
    assert result.status == "ok"
    payload = result.to_payload()
    assert payload["status"] == "ok"
    assert payload["runtimePath"] == ".1c-dev/runtime/main"
    assert payload["steps"] == ["metadata", "modules"]
    assert "duration" in payload


def test_run_check_metadata_and_modules_both_fail(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert bootstrap_configuration_project(target, name="Shop").status == "ok"
    _ensure_ib(target)
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    onecv8 = tmp_path / "1cv8"
    onecv8.write_text("", encoding="utf-8")

    result = run_check(
        target,
        discover=lambda: _fake_discovery(ibcmd=ibcmd, onecv8=onecv8),
        run=_fail_check_run,
        modules_fn=_fake_modules_fail,
    )
    assert result.status == "failed"
    assert result.steps == ["metadata", "modules"]
    assert len(result.diagnostics) >= 2
    assert any("метаданные" in d.get("message", "").lower() for d in result.diagnostics)
    assert any(d.get("line") == 2 for d in result.diagnostics)


def test_run_check_modules_failure_only(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert bootstrap_configuration_project(target, name="Shop").status == "ok"
    _ensure_ib(target)
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    onecv8 = tmp_path / "1cv8"
    onecv8.write_text("", encoding="utf-8")

    result = run_check(
        target,
        discover=lambda: _fake_discovery(ibcmd=ibcmd, onecv8=onecv8),
        run=_ok_run,
        modules_fn=_fake_modules_fail,
    )
    assert result.status == "failed"
    assert any(d.get("code") == CODE_CHECK_FAILED for d in result.diagnostics)
    assert any(d.get("object") == "CommonModule.BrokenServer" for d in result.diagnostics)


def test_check_payload_matches_schema(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert bootstrap_configuration_project(target, name="Shop").status == "ok"
    _ensure_ib(target)
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    onecv8 = tmp_path / "1cv8"
    onecv8.write_text("", encoding="utf-8")
    result = run_check(
        target,
        discover=lambda: _fake_discovery(ibcmd=ibcmd, onecv8=onecv8),
        run=_ok_run,
        modules_fn=_fake_modules_ok,
    )
    schema = json.loads((SCHEMAS / "check.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    diag = json.loads((SCHEMAS / "diagnostics.schema.json").read_text(encoding="utf-8"))
    schema["properties"]["diagnostics"]["items"] = diag
    Draft202012Validator(schema).validate(result.to_payload())


def test_cli_check_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert bootstrap_configuration_project(target, name="Shop").status == "ok"
    _ensure_ib(target)
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    onecv8 = tmp_path / "1cv8"
    onecv8.write_text("", encoding="utf-8")
    monkeypatch.chdir(target)

    monkeypatch.setattr(
        "core.check.run.discover_environment",
        lambda: _fake_discovery(ibcmd=ibcmd, onecv8=onecv8),
    )
    monkeypatch.setattr("core.check.run.check_config", _fake_check_ok)
    monkeypatch.setattr("core.check.run.check_modules", _fake_modules_ok)

    result = runner.invoke(app, ["check", "--output", "json"])
    assert result.exit_code == SUCCESS
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["steps"] == ["metadata", "modules"]


def test_cli_check_mode_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert bootstrap_configuration_project(target, name="Shop").status == "ok"
    _ensure_ib(target)
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    onecv8 = tmp_path / "1cv8"
    onecv8.write_text("", encoding="utf-8")
    monkeypatch.chdir(target)
    monkeypatch.setattr(
        "core.check.run.discover_environment",
        lambda: _fake_discovery(ibcmd=ibcmd, onecv8=onecv8),
    )
    monkeypatch.setattr("core.check.run.check_config", _fake_check_ok)
    captured: dict[str, Any] = {}

    def capture_modules(*_a: Any, **kwargs: Any) -> None:
        captured["modes"] = kwargs.get("modes")

    monkeypatch.setattr("core.check.run.check_modules", capture_modules)
    result = runner.invoke(
        app,
        ["check", "--mode", "Server", "--mode", "ThinClient", "--output", "json"],
    )
    assert result.exit_code == SUCCESS
    assert captured["modes"] == ["Server", "ThinClient"]


def _fake_check_ok(*_args: Any, **_kwargs: Any) -> IbcmdRunResult:
    return IbcmdRunResult(returncode=0, stdout="ok", stderr="", argv=["ibcmd", "check"])


def test_cli_check_missing_ibcmd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert bootstrap_configuration_project(target, name="Shop").status == "ok"
    _ensure_ib(target)
    monkeypatch.chdir(target)
    monkeypatch.setattr(
        "core.check.run.discover_environment",
        lambda: _fake_discovery(ibcmd=None, onecv8=Path("/fake/1cv8")),
    )
    result = runner.invoke(app, ["check", "--output", "json"])
    assert result.exit_code == ENV_UNAVAILABLE
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"


def test_cli_check_missing_onecv8(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert bootstrap_configuration_project(target, name="Shop").status == "ok"
    _ensure_ib(target)
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    monkeypatch.chdir(target)
    monkeypatch.setattr(
        "core.check.run.discover_environment",
        lambda: _fake_discovery(ibcmd=ibcmd, onecv8=None),
    )
    result = runner.invoke(app, ["check", "--output", "json"])
    assert result.exit_code == ENV_UNAVAILABLE
    payload = json.loads(result.stdout)
    assert any(d.get("code") == CODE_CHECK_ONECV8_MISSING for d in payload["diagnostics"])


def test_cli_check_failure_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert bootstrap_configuration_project(target, name="Shop").status == "ok"
    _ensure_ib(target)
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    onecv8 = tmp_path / "1cv8"
    onecv8.write_text("", encoding="utf-8")
    monkeypatch.chdir(target)
    monkeypatch.setattr(
        "core.check.run.discover_environment",
        lambda: _fake_discovery(ibcmd=ibcmd, onecv8=onecv8),
    )
    monkeypatch.setattr("core.check.run.check_config", _fake_check_fail)
    monkeypatch.setattr("core.check.run.check_modules", _fake_modules_ok)
    result = runner.invoke(app, ["check", "--output", "json"])
    assert result.exit_code == CHECK_FAILURE


def _fake_check_fail(*_args: Any, **_kwargs: Any) -> IbcmdRunResult:
    from adapters.platform_ibcmd import IbcmdError

    raise IbcmdError(
        "boom",
        code=CODE_CHECK_FAILED,
        diagnostics=[error("ошибка метаданных", code=CODE_CHECK_FAILED, source="platform")],
        step="check",
    )


def test_cli_check_no_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["check", "--output", "json"])
    assert result.exit_code == PROJECT_ERROR


def test_cli_check_missing_ib_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert bootstrap_configuration_project(target, name="Shop").status == "ok"
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    onecv8 = tmp_path / "1cv8"
    onecv8.write_text("", encoding="utf-8")
    monkeypatch.chdir(target)
    monkeypatch.setattr(
        "core.check.run.discover_environment",
        lambda: _fake_discovery(ibcmd=ibcmd, onecv8=onecv8),
    )
    result = runner.invoke(app, ["check", "--output", "json"])
    assert result.exit_code == PROJECT_ERROR


@pytest.mark.integration
def test_integration_ibcmd_check(tmp_path: Path) -> None:
    """Real build + check (metadata + modules); skip if platform unavailable."""
    from adapters.platform import discover_environment

    discovery = discover_environment()
    if not discovery.ibcmd.found or discovery.ibcmd.path is None:
        pytest.skip("ibcmd не найден — integration check пропущен")
    if not discovery.onecv8.found or discovery.onecv8.path is None:
        pytest.skip("1cv8 не найден — integration check пропущен")

    target = tmp_path / "shop"
    target.mkdir()
    assert bootstrap_configuration_project(target, name="Shop").status == "ok"

    build = run_build(target)
    assert build.status == "ok", build.to_payload()

    result = run_check(target)
    assert result.status == "ok", result.to_payload()
    assert result.steps == ["metadata", "modules"]
    assert (target / ".1c-dev" / "runtime" / "main" / IB_MARKER).is_file()


@pytest.mark.integration
def test_integration_check_modules_catches_syntax(tmp_path: Path) -> None:
    """Broken BSL: ibcmd metadata may pass; /CheckModules must fail."""
    from adapters.platform import discover_environment
    from adapters.source.xmlgen.resolve import resolve_jar, resolve_java

    jar = resolve_jar()
    java = resolve_java()
    if not jar.found or not java.found:
        pytest.skip("xml-gen jar / Java недоступны")

    discovery = discover_environment()
    if not discovery.ibcmd.found or discovery.ibcmd.path is None:
        pytest.skip("ibcmd не найден")
    if not discovery.onecv8.found or discovery.onecv8.path is None:
        pytest.skip("1cv8 не найден")

    target = tmp_path / "broken"
    target.mkdir()
    assert bootstrap_configuration_project(target, name="Broken", ide_target="none").status == "ok"

    created = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="CommonModule.BrokenServer",
            synonym="Сломанный",
            server=True,
            client=False,
        ),
    )
    assert created.status == "ok", created.diagnostics

    bsl = target / "src/cf/CommonModules/BrokenServer/Ext/Module.bsl"
    bsl.write_bytes(
        b"\xef\xbb\xbf"
        + "Процедура Тест() Экспорт\n    А = ;\nКонецПроцедуры\n".encode()
    )

    build = run_build(target)
    assert build.status == "ok", build.to_payload()

    result = run_check(target)
    assert result.status == "failed", result.to_payload()
    assert "modules" in result.steps
    assert any(
        d.get("object") == "CommonModule.BrokenServer" and d.get("line") == 2
        for d in result.diagnostics
    )
