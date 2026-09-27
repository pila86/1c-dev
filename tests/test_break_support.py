"""Tests for break-support strip (ADR-020, #74)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from adapters.platform.discovery import DiscoveryResult, PlatformInfo, ToolInfo
from adapters.platform_ibcmd.constants import IB_MARKER
from cli.main import app
from core.break_support import run_break_support, strip_parent_configurations
from core.break_support.constants import CODE_ALREADY_OFF_SUPPORT, CODE_SUPPORT_REMOVED
from core.exit_codes import PROJECT_ERROR, SUCCESS
from core.import_cf import run_import
from core.project import init_project
from core.project.constants import MANIFEST_NAME

runner = CliRunner()
FIXTURES = Path(__file__).parent / "fixtures"
BREAK_SUPPORT_FIXTURE = FIXTURES / "break_support_source"


def _fake_discovery(*, ibcmd: Path | None) -> DiscoveryResult:
    return DiscoveryResult(
        platform=PlatformInfo(found=True, version="8.3.25.1560", path=Path("/opt/1cv8")),
        ibcmd=ToolInfo(found=ibcmd is not None, path=ibcmd),
        onecv8=ToolInfo(found=False, path=None),
        onecv8c=ToolInfo(found=False, path=None),
    )


def _copy_fixture(dest: Path) -> Path:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(BREAK_SUPPORT_FIXTURE, dest)
    return dest


def test_strip_parent_configurations_fixture(tmp_path: Path) -> None:
    source = _copy_fixture(tmp_path / "src")
    catalog = source / "Catalogs" / "Products.xml"
    catalog_bytes = catalog.read_bytes()
    cfg = source / "Configuration.xml"
    cfg_bytes = cfg.read_bytes()

    removed, diags = strip_parent_configurations(source, root=tmp_path)

    assert not (source / "Ext" / "ParentConfigurations.bin").exists()
    assert not (source / "ParentConfigurations").exists()
    assert catalog.is_file()
    assert catalog.read_bytes() == catalog_bytes
    assert cfg.read_bytes() == cfg_bytes
    assert "src/Ext/ParentConfigurations.bin" in removed
    assert "src/ParentConfigurations" in removed
    assert all(d.get("code") == CODE_SUPPORT_REMOVED for d in diags)
    assert len(removed) == 2


def test_strip_idempotent(tmp_path: Path) -> None:
    source = _copy_fixture(tmp_path / "src")
    strip_parent_configurations(source, root=tmp_path)
    removed, diags = strip_parent_configurations(source, root=tmp_path)
    assert removed == []
    assert any(d.get("code") == CODE_ALREADY_OFF_SUPPORT for d in diags)
    assert any(d.get("severity") == "warning" for d in diags)


def test_run_import_break_support_strips(tmp_path: Path) -> None:
    target = tmp_path / "imported"
    target.mkdir()
    cf_path = tmp_path / "configuration.cf"
    cf_path.write_bytes(b"CF")
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")

    def import_fn(
        _ibcmd: Path,
        *,
        db_path: Path,
        data_path: Path,
        cf_path: Path,
        source_dir: Path,
        run: Any = None,
    ) -> list[str]:
        _copy_fixture(source_dir)
        db_path.mkdir(parents=True, exist_ok=True)
        (db_path / IB_MARKER).write_bytes(b"")
        return ["create", "load", "apply", "export"]

    result = run_import(
        target,
        from_path=cf_path,
        break_support=True,
        discover=lambda: _fake_discovery(ibcmd=ibcmd),
        import_fn=import_fn,
    )
    assert result.status == "ok", result.to_payload()
    source = target / "src" / "cf"
    assert not (source / "Ext" / "ParentConfigurations.bin").exists()
    assert not (source / "ParentConfigurations").exists()
    assert (source / "Catalogs" / "Products.xml").is_file()
    assert result.removed
    assert any(d.get("code") == CODE_SUPPORT_REMOVED for d in result.diagnostics)
    payload = result.to_payload()
    assert "removed" in payload


def test_run_import_without_break_support_keeps_artifacts(tmp_path: Path) -> None:
    target = tmp_path / "imported"
    target.mkdir()
    cf_path = tmp_path / "configuration.cf"
    cf_path.write_bytes(b"CF")
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")

    def import_fn(
        _ibcmd: Path,
        *,
        db_path: Path,
        data_path: Path,
        cf_path: Path,
        source_dir: Path,
        run: Any = None,
    ) -> list[str]:
        _copy_fixture(source_dir)
        db_path.mkdir(parents=True, exist_ok=True)
        (db_path / IB_MARKER).write_bytes(b"")
        return ["create", "load", "apply", "export"]

    result = run_import(
        target,
        from_path=cf_path,
        break_support=False,
        discover=lambda: _fake_discovery(ibcmd=ibcmd),
        import_fn=import_fn,
    )
    assert result.status == "ok", result.to_payload()
    source = target / "src" / "cf"
    assert (source / "Ext" / "ParentConfigurations.bin").is_file()
    assert (source / "ParentConfigurations").is_dir()
    assert result.removed == []


def test_run_import_break_support_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "imported"
    target.mkdir()
    cf_path = tmp_path / "configuration.cf"
    cf_path.write_bytes(b"CF")
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")

    def import_fn(
        _ibcmd: Path,
        *,
        db_path: Path,
        data_path: Path,
        cf_path: Path,
        source_dir: Path,
        run: Any = None,
    ) -> list[str]:
        source_dir.mkdir(parents=True, exist_ok=True)
        (source_dir / "Configuration.xml").write_text("<MetaDataObject/>", encoding="utf-8")
        db_path.mkdir(parents=True, exist_ok=True)
        (db_path / IB_MARKER).write_bytes(b"")
        return ["create", "load", "apply", "export"]

    result = run_import(
        target,
        from_path=cf_path,
        break_support=True,
        discover=lambda: _fake_discovery(ibcmd=ibcmd),
        import_fn=import_fn,
    )
    assert result.status == "ok", result.to_payload()
    assert result.removed == []
    assert any(d.get("code") == CODE_ALREADY_OFF_SUPPORT for d in result.diagnostics)


def test_run_break_support_cli_and_core(tmp_path: Path, monkeypatch: Any) -> None:
    assert init_project(tmp_path, project_type="configuration", name="Shop").status == "ok"
    source = tmp_path / "src" / "cf"
    # replace skeleton with fixture content
    shutil.rmtree(source)
    _copy_fixture(source)

    core_result = run_break_support(tmp_path)
    assert core_result.status == "ok"
    assert core_result.removed
    assert not (source / "Ext" / "ParentConfigurations.bin").exists()

    # second call idempotent
    again = run_break_support(tmp_path)
    assert again.status == "ok"
    assert again.removed == []
    assert any(d.get("code") == CODE_ALREADY_OFF_SUPPORT for d in again.diagnostics)

    # restore artifacts and exercise CLI
    shutil.rmtree(source)
    _copy_fixture(source)
    monkeypatch.chdir(tmp_path)
    cli = runner.invoke(app, ["source", "break-support", "--output", "json"])
    assert cli.exit_code == SUCCESS, cli.output
    payload = json.loads(cli.output)
    assert payload["status"] == "ok"
    assert payload["removed"]
    assert not (source / "Ext" / "ParentConfigurations.bin").exists()


def test_cli_source_break_support_no_manifest(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["source", "break-support", "--output", "json"])
    assert result.exit_code == PROJECT_ERROR
    payload = json.loads(result.output)
    assert payload["status"] == "failed"


def test_cli_project_import_break_support(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    cf_path = tmp_path / "configuration.cf"
    cf_path.write_bytes(b"CF")
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")

    def fake_import(
        _ibcmd: Path,
        *,
        db_path: Path,
        data_path: Path,
        cf_path: Path,
        source_dir: Path,
        run: Any = None,
    ) -> list[str]:
        _copy_fixture(source_dir)
        db_path.mkdir(parents=True, exist_ok=True)
        (db_path / IB_MARKER).write_bytes(b"")
        return ["create", "load", "apply", "export"]

    monkeypatch.setattr(
        "core.import_cf.run.discover_environment",
        lambda: _fake_discovery(ibcmd=ibcmd),
    )
    monkeypatch.setattr("core.import_cf.run.import_cf_with_ibcmd", fake_import)

    result = runner.invoke(
        app,
        [
            "project",
            "import",
            "--from",
            str(cf_path),
            "--break-support",
            "--output",
            "json",
        ],
    )
    assert result.exit_code == SUCCESS, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload.get("removed")
    assert not (tmp_path / "src" / "cf" / "Ext" / "ParentConfigurations.bin").exists()
    assert (tmp_path / MANIFEST_NAME).is_file()
