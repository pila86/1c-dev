"""Tests for publish.up / down / status / url (ADR-025 / #89)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from adapters.apache.client import ApacheRunResult
from adapters.ibsrv.client import IbsrvRunResult
from adapters.platform.discovery import DiscoveryResult, PlatformInfo, ToolInfo
from adapters.platform_ibcmd.client import IbcmdRunResult
from adapters.platform_ibcmd.constants import IB_MARKER
from cli.main import app
from core.exit_codes import SUCCESS
from core.project import init_project
from core.publish import (
    CODE_APACHE_FAILED,
    CODE_BACKEND_UNSUPPORTED,
    CODE_IBSRV_MISSING,
    CODE_PROJECT,
    CODE_WEBINST_MISSING,
    run_down,
    run_status,
    run_up,
)
from core.toolchain.resolve import ApacheResolve
from tests.helpers_project import bootstrap_configuration_project

runner = CliRunner()


def _fake_discovery(
    *,
    ibcmd: Path | None,
    ibsrv: Path | None,
    webinst: Path | None = None,
    platform_path: Path | None = None,
) -> DiscoveryResult:
    return DiscoveryResult(
        platform=PlatformInfo(
            found=True,
            version="8.3.25.1560",
            path=platform_path or Path("/opt/1cv8"),
        ),
        ibcmd=ToolInfo(found=ibcmd is not None, path=ibcmd),
        onecv8=ToolInfo(found=False, path=None),
        onecv8c=ToolInfo(found=False, path=None),
        ibsrv=ToolInfo(found=ibsrv is not None, path=ibsrv),
        webinst=ToolInfo(found=webinst is not None, path=webinst),
    )


def _platform_bin_with_ws(tmp_path: Path) -> Path:
    """Create fake platform bin dir with wsap24.so; return ibcmd path."""
    bin_dir = tmp_path / "platform-bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "wsap24.so").write_bytes(b"")
    ibcmd = bin_dir / "ibcmd"
    if not ibcmd.exists():
        ibcmd.write_text("", encoding="utf-8")
    return ibcmd


def _init_with_ib(tmp_path: Path) -> Path:
    target = tmp_path / "shop"
    target.mkdir()
    assert bootstrap_configuration_project(target, name="Shop").status == "ok"
    ib = target / ".1c-dev" / "runtime" / "main"
    ib.mkdir(parents=True, exist_ok=True)
    (ib / IB_MARKER).write_bytes(b"")
    return target


def _force_ibsrv_default(root: Path) -> None:
    """Replace default webinst publish section with local-ibsrv for ibsrv unit tests."""
    manifest = root / ".1c-dev" / "project.yaml"
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    runtime_id = data["runtimes"][0]["id"]
    data["publish"] = {
        "default": "local-ibsrv",
        "profiles": {
            "local-ibsrv": {
                "backend": "ibsrv",
                "port": 8314,
                "runtime": runtime_id,
                "config": ".1c-dev/publish/local-ibsrv/ibsrv.yaml",
            }
        },
    }
    manifest.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


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
    _force_ibsrv_default(root)
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
    _force_ibsrv_default(root)
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
    _force_ibsrv_default(root)
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


def test_publish_webinst_up(tmp_path: Path) -> None:
    root = _init_with_ib(tmp_path)
    db = root / ".1c-dev" / "runtime" / "main"
    manifest = root / ".1c-dev" / "project.yaml"
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    runtime_id = data["runtimes"][0]["id"]
    data["publish"] = {
        "default": "apache",
        "profiles": {
            "apache": {
                "backend": "webinst",
                "runtime": runtime_id,
                "port": 8315,
                "wsdir": "shop",
            }
        },
    }
    manifest.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")

    ibcmd = _platform_bin_with_ws(tmp_path)
    httpd = tmp_path / "httpd"
    httpd.write_text("", encoding="utf-8")
    apache_home = tmp_path / "apache-home"
    (apache_home / "bin").mkdir(parents=True)
    (apache_home / "bin" / "httpd").write_text("#!/bin/sh\n", encoding="utf-8")
    (apache_home / "modules").mkdir()
    for name in ("mod_mpm_event.so", "mod_authz_core.so", "mod_alias.so"):
        (apache_home / "modules" / name).write_bytes(b"")

    captured_httpd: list[list[str]] = []

    def ap_run(argv: list[str]) -> ApacheRunResult:
        captured_httpd.append(argv)
        profile = root / ".1c-dev" / "publish" / "apache"
        (profile / "httpd.pid").write_text("5555\n", encoding="utf-8")
        return ApacheRunResult(0, "", "", argv)

    result = run_up(
        root,
        discover=lambda: _fake_discovery(ibcmd=ibcmd, ibsrv=None, webinst=None),
        apache_run=ap_run,
        apache_home=ApacheResolve(
            found=True,
            home=apache_home,
            httpd=httpd,
            modules_dir=apache_home / "modules",
            source="cache",
        ),
        is_alive=lambda pid: pid == 5555,
        settle_seconds=0,
        wait_lock_seconds=1.0,
    )
    assert result.status == "ok"
    assert result.running is True
    assert result.pid == 5555
    assert result.url == "http://127.0.0.1:8315/shop"
    assert captured_httpd
    conf = (root / ".1c-dev" / "publish" / "apache" / "httpd.conf").read_text(
        encoding="utf-8"
    )
    assert 'Alias "/shop"' in conf
    assert "SetHandler 1c-application" in conf
    vrd = root / ".1c-dev" / "publish" / "apache" / "www" / "default.vrd"
    assert vrd.is_file()
    assert str(db.resolve()) in vrd.read_text(encoding="utf-8").replace("&quot;", '"')


def test_publish_webinst_missing_ws_module(tmp_path: Path) -> None:
    root = _init_with_ib(tmp_path)
    manifest = root / ".1c-dev" / "project.yaml"
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    runtime_id = data["runtimes"][0]["id"]
    data["publish"] = {
        "default": "apache",
        "profiles": {
            "apache": {
                "backend": "webinst",
                "runtime": runtime_id,
            }
        },
    }
    manifest.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    result = run_up(
        root,
        discover=lambda: _fake_discovery(ibcmd=None, ibsrv=None, webinst=None),
        apache_home=ApacheResolve(
            found=True,
            home=tmp_path,
            httpd=tmp_path / "httpd",
            modules_dir=tmp_path,
            source="cache",
        ),
        settle_seconds=0,
        wait_lock_seconds=0,
    )
    assert result.status == "failed"
    assert any(d.get("code") == CODE_WEBINST_MISSING for d in result.diagnostics)


def test_publish_webinst_missing_apache(tmp_path: Path) -> None:
    root = _init_with_ib(tmp_path)
    manifest = root / ".1c-dev" / "project.yaml"
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    runtime_id = data["runtimes"][0]["id"]
    data["publish"] = {
        "default": "apache",
        "profiles": {
            "apache": {
                "backend": "webinst",
                "runtime": runtime_id,
            }
        },
    }
    manifest.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    ibcmd = _platform_bin_with_ws(tmp_path)
    result = run_up(
        root,
        discover=lambda: _fake_discovery(ibcmd=ibcmd, ibsrv=None, webinst=None),
        apache_home=ApacheResolve(found=False),
        settle_seconds=0,
        wait_lock_seconds=0,
    )
    assert result.status == "failed"
    assert any(d.get("code") == CODE_APACHE_FAILED for d in result.diagnostics)


def test_publish_up_missing_ibsrv(tmp_path: Path) -> None:
    root = _init_with_ib(tmp_path)
    _force_ibsrv_default(root)
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
    assert payload["profile"] == "local-webinst"


def test_cli_publish_help() -> None:
    result = runner.invoke(app, ["publish", "--help"])
    assert result.exit_code == 0
    assert "up" in result.stdout
    assert "down" in result.stdout


def test_publish_up_backend_ensures_webinst_profile(tmp_path: Path) -> None:
    """--backend webinst creates local-webinst when only local-ibsrv exists."""
    root = _init_with_ib(tmp_path)
    _force_ibsrv_default(root)
    manifest = root / ".1c-dev" / "project.yaml"
    before = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    assert "local-webinst" not in before.get("publish", {}).get("profiles", {})

    ibcmd = _platform_bin_with_ws(tmp_path)
    apache_home = tmp_path / "apache-home"
    (apache_home / "bin").mkdir(parents=True)
    (apache_home / "bin" / "httpd").write_text("#!/bin/sh\n", encoding="utf-8")
    (apache_home / "modules").mkdir()
    for name in ("mod_mpm_event.so", "mod_authz_core.so", "mod_alias.so"):
        (apache_home / "modules" / name).write_bytes(b"")

    def apache_run(argv: list[str]) -> ApacheRunResult:
        pid_file = root / ".1c-dev" / "publish" / "local-webinst" / "httpd.pid"
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text("7777\n", encoding="utf-8")
        return ApacheRunResult(returncode=0, stdout="", stderr="", argv=argv)

    result = run_up(
        root,
        backend="webinst",
        discover=lambda: _fake_discovery(ibcmd=ibcmd, ibsrv=None, webinst=None),
        apache_run=apache_run,
        apache_home=ApacheResolve(
            found=True,
            home=apache_home,
            httpd=apache_home / "bin" / "httpd",
            modules_dir=apache_home / "modules",
            source="cache",
        ),
        is_alive=lambda pid: pid == 7777,
        settle_seconds=0,
        wait_lock_seconds=1.0,
    )
    assert result.status == "ok"
    assert result.profile_id == "local-webinst"
    assert result.backend == "webinst"
    assert result.url == "http://127.0.0.1:8315/local-webinst"

    after = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    assert after["publish"]["default"] == "local-ibsrv"
    assert after["publish"]["profiles"]["local-webinst"]["backend"] == "webinst"
    assert after["publish"]["profiles"]["local-webinst"]["runtime"] == before["runtimes"][0]["id"]


def test_publish_up_backend_selects_existing(tmp_path: Path) -> None:
    root = _init_with_ib(tmp_path)
    _force_ibsrv_default(root)
    manifest = root / ".1c-dev" / "project.yaml"
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    runtime_id = data["runtimes"][0]["id"]
    data["publish"]["profiles"]["custom-wi"] = {
        "backend": "webinst",
        "runtime": runtime_id,
        "port": 8315,
        "wsdir": "app",
    }
    manifest.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")

    ibcmd = _platform_bin_with_ws(tmp_path)
    apache_home = tmp_path / "apache-home"
    (apache_home / "bin").mkdir(parents=True)
    (apache_home / "bin" / "httpd").write_text("#!/bin/sh\n", encoding="utf-8")
    (apache_home / "modules").mkdir()
    for name in ("mod_mpm_event.so", "mod_authz_core.so", "mod_alias.so"):
        (apache_home / "modules" / name).write_bytes(b"")

    def apache_run(argv: list[str]) -> ApacheRunResult:
        pid_file = root / ".1c-dev" / "publish" / "custom-wi" / "httpd.pid"
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text("8888\n", encoding="utf-8")
        return ApacheRunResult(returncode=0, stdout="", stderr="", argv=argv)

    result = run_up(
        root,
        backend="webinst",
        discover=lambda: _fake_discovery(ibcmd=ibcmd, ibsrv=None, webinst=None),
        apache_run=apache_run,
        apache_home=ApacheResolve(
            found=True,
            home=apache_home,
            httpd=apache_home / "bin" / "httpd",
            modules_dir=apache_home / "modules",
            source="cache",
        ),
        is_alive=lambda pid: pid == 8888,
        settle_seconds=0,
        wait_lock_seconds=1.0,
    )
    assert result.status == "ok"
    assert result.profile_id == "custom-wi"
    assert result.url == "http://127.0.0.1:8315/app"
    after = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    assert "local-webinst" not in after["publish"]["profiles"]


def test_publish_up_profile_backend_mismatch(tmp_path: Path) -> None:
    root = _init_with_ib(tmp_path)
    _force_ibsrv_default(root)
    result = run_up(
        root,
        profile_id="local-ibsrv",
        backend="webinst",
        discover=lambda: _fake_discovery(ibcmd=None, ibsrv=None),
        settle_seconds=0,
        wait_lock_seconds=0,
    )
    assert result.status == "failed"
    assert any(d.get("code") == CODE_BACKEND_UNSUPPORTED for d in result.diagnostics)


def test_cli_publish_up_backend_help() -> None:
    result = runner.invoke(app, ["publish", "up", "--help"])
    assert result.exit_code == 0
    # Rich may insert ANSI mid-token (e.g. styled "--backend") when COLUMNS is set (CI).
    plain = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", result.stdout)
    assert "--backend" in plain
