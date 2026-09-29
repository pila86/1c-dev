"""Tests for publish.up / down / status / url (ADR-025 / #89)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from adapters.ibsrv.client import IbsrvRunResult
from adapters.platform.discovery import DiscoveryResult, PlatformInfo, ToolInfo
from adapters.platform_ibcmd.client import IbcmdRunResult
from adapters.platform_ibcmd.constants import IB_MARKER
from cli.main import app
from core.exit_codes import SUCCESS
from core.project import init_project
from core.publish import (
    CODE_BACKEND_UNSUPPORTED,
    CODE_IBSRV_MISSING,
    CODE_PROJECT,
    run_down,
    run_status,
    run_up,
)

runner = CliRunner()


def _fake_discovery(*, ibcmd: Path | None, ibsrv: Path | None) -> DiscoveryResult:
    return DiscoveryResult(
        platform=PlatformInfo(found=True, version="8.3.25.1560", path=Path("/opt/1cv8")),
        ibcmd=ToolInfo(found=ibcmd is not None, path=ibcmd),
        onecv8=ToolInfo(found=False, path=None),
        onecv8c=ToolInfo(found=False, path=None),
        ibsrv=ToolInfo(found=ibsrv is not None, path=ibsrv),
    )


def _init_with_ib(tmp_path: Path) -> Path:
    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(target, project_type="configuration", name="Shop").status == "ok"
    ib = target / ".1c-dev" / "runtime" / "main"
    ib.mkdir(parents=True, exist_ok=True)
    (ib / IB_MARKER).write_bytes(b"")
    return target


def _write_yaml(path: Path, *, db_path: Path, port: int = 8314) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "server": {"address": "localhost", "port": port},
                "database": {"path": str(db_path)},
                "http": {"base": "/"},
            }
        ),
        encoding="utf-8",
    )


def test_publish_up_idempotent(tmp_path: Path) -> None:
    root = _init_with_ib(tmp_path)
    db = root / ".1c-dev" / "runtime" / "main"
    cfg = root / ".1c-dev" / "publish" / "local-ibsrv" / "ibsrv.yaml"
    data = root / ".1c-dev" / "publish" / "local-ibsrv" / "data"
    data.mkdir(parents=True)
    _write_yaml(cfg, db_path=db)
    (data / "lock.pid").write_text("9991\n", encoding="utf-8")

    starts: list[list[str]] = []

    def ibsrv_run(argv: list[str]) -> IbsrvRunResult:
        starts.append(argv)
        return IbsrvRunResult(returncode=0, stdout="", stderr="", argv=argv)

    result = run_up(
        root,
        discover=lambda: _fake_discovery(
            ibcmd=tmp_path / "ibcmd",
            ibsrv=tmp_path / "ibsrv",
        ),
        ibsrv_run=ibsrv_run,
        is_alive=lambda pid: pid == 9991,
        settle_seconds=0,
        wait_lock_seconds=0,
    )
    assert result.status == "ok"
    assert result.running is True
    assert result.pid == 9991
    assert result.url == "http://localhost:8314/"
    assert starts == []


def test_publish_up_starts_daemon(tmp_path: Path) -> None:
    root = _init_with_ib(tmp_path)
    db = root / ".1c-dev" / "runtime" / "main"
    ibcmd = tmp_path / "ibcmd"
    ibsrv = tmp_path / "ibsrv"
    ibcmd.write_text("", encoding="utf-8")
    ibsrv.write_text("", encoding="utf-8")
    captured_ibcmd: list[list[str]] = []
    captured_ibsrv: list[list[str]] = []

    def ibcmd_run(argv: list[str]) -> IbcmdRunResult:
        captured_ibcmd.append(argv)
        out = next(a.split("=", 1)[1] for a in argv if a.startswith("--out="))
        _write_yaml(Path(out), db_path=db)
        return IbcmdRunResult(returncode=0, stdout="", stderr="", argv=argv)

    def ibsrv_run(argv: list[str]) -> IbsrvRunResult:
        captured_ibsrv.append(argv)
        data = next(a.split("=", 1)[1] for a in argv if a.startswith("--data="))
        Path(data).mkdir(parents=True, exist_ok=True)
        (Path(data) / "lock.pid").write_text("4242\n", encoding="utf-8")
        return IbsrvRunResult(returncode=0, stdout="", stderr="", argv=argv)

    result = run_up(
        root,
        discover=lambda: _fake_discovery(ibcmd=ibcmd, ibsrv=ibsrv),
        ibcmd_run=ibcmd_run,
        ibsrv_run=ibsrv_run,
        is_alive=lambda pid: pid == 4242,
        settle_seconds=0,
        wait_lock_seconds=1.0,
    )
    assert result.status == "ok"
    assert result.running is True
    assert result.pid == 4242
    assert result.url == "http://localhost:8314/"
    assert captured_ibcmd
    assert "server" in captured_ibcmd[0]
    assert captured_ibsrv
    assert "--disable-direct-gate" in captured_ibsrv[0]


def test_publish_down_clears_lock(tmp_path: Path) -> None:
    root = _init_with_ib(tmp_path)
    data = root / ".1c-dev" / "publish" / "local-ibsrv" / "data"
    data.mkdir(parents=True)
    (data / "lock.pid").write_text("777\n", encoding="utf-8")
    terminated: list[int] = []

    result = run_down(
        root,
        is_alive=lambda pid: pid == 777 and 777 not in terminated,
        terminate_fn=lambda pid: terminated.append(pid) or True,
    )
    assert result.status == "ok"
    assert result.running is False
    assert terminated == [777]
    assert not (data / "lock.pid").exists()


def test_publish_missing_section(tmp_path: Path) -> None:
    root = tmp_path / "bare"
    root.mkdir()
    assert init_project(root, project_type="extension", name="Ext").status == "ok"
    result = run_status(root)
    assert result.status == "failed"
    assert any(d.get("code") == CODE_PROJECT for d in result.diagnostics)


def test_publish_webinst_unsupported(tmp_path: Path) -> None:
    root = _init_with_ib(tmp_path)
    manifest = root / ".1c-dev" / "project.yaml"
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    data["publish"] = {
        "default": "apache",
        "profiles": {
            "apache": {
                "backend": "webinst",
                "runtime": "main-dev",
            }
        },
    }
    # runtime id from init is main-dev pattern — check actual
    runtime_id = data["runtimes"][0]["id"]
    data["publish"]["profiles"]["apache"]["runtime"] = runtime_id
    manifest.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    result = run_up(root)
    assert result.status == "failed"
    assert any(d.get("code") == CODE_BACKEND_UNSUPPORTED for d in result.diagnostics)


def test_publish_up_missing_ibsrv(tmp_path: Path) -> None:
    root = _init_with_ib(tmp_path)
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    result = run_up(
        root,
        discover=lambda: _fake_discovery(ibcmd=ibcmd, ibsrv=None),
        settle_seconds=0,
        wait_lock_seconds=0,
    )
    assert result.status == "failed"
    assert any(d.get("code") == CODE_IBSRV_MISSING for d in result.diagnostics)


def test_cli_publish_status_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _init_with_ib(tmp_path)
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["publish", "status", "--output", "json"])
    assert result.exit_code == SUCCESS
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["running"] is False
    assert payload["profile"] == "local-ibsrv"


def test_cli_publish_help() -> None:
    result = runner.invoke(app, ["publish", "--help"])
    assert result.exit_code == 0
    assert "up" in result.stdout
    assert "down" in result.stdout
