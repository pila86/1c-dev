"""Tests for extension add / list (ADR-023 / #88)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from adapters.platform.discovery import DiscoveryResult, PlatformInfo, ToolInfo
from adapters.platform_ibcmd.client import IbcmdRunResult
from adapters.platform_ibcmd.constants import IB_MARKER
from cli.main import app
from core.exit_codes import PROJECT_ERROR, SUCCESS
from core.extension import add_extension, run_extension_list
from core.project import init_project

runner = CliRunner()


def _init_config_project(target: Path, *, name: str = "Shop") -> None:
    assert init_project(target, project_type="configuration", name=name).status == "ok"
    from core.configuration import add_configuration

    assert (
        add_configuration(
            target, config_id="main", name=name, source_path="src/cf"
        ).status
        == "ok"
    )


def _fake_discovery(*, ibcmd: Path | None) -> DiscoveryResult:
    return DiscoveryResult(
        platform=PlatformInfo(found=True, version="8.3.25.1560", path=Path("/opt/1cv8")),
        ibcmd=ToolInfo(found=ibcmd is not None, path=ibcmd),
        onecv8=ToolInfo(found=False, path=None),
        onecv8c=ToolInfo(found=False, path=None),
        ibsrv=ToolInfo(found=False, path=None),
        webinst=ToolInfo(found=False, path=None),
    )


def test_add_extension_to_configuration(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    _init_config_project(target)

    result = add_extension(target, ext_id="custom", name="CustomExt", purpose="product")
    assert result.status == "ok", result.diagnostics
    assert (target / "src" / "cfe" / "custom" / "Configuration.xml").is_file()
    assert (
        target / "src" / "cfe" / "custom" / "Roles" / "CustomExt_MainRole.xml"
    ).is_file()

    data = yaml.safe_load(
        (target / ".1c-dev" / "project.yaml").read_text(encoding="utf-8")
    )
    exts = data["configurations"][0]["extensions"]
    assert len(exts) == 1
    assert exts[0]["id"] == "custom"
    assert exts[0]["name"] == "CustomExt"
    assert exts[0]["source"]["path"] == "src/cfe/custom"


def test_add_extension_duplicate(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    _init_config_project(target)
    assert add_extension(target, ext_id="custom", name="CustomExt").status == "ok"
    second = add_extension(target, ext_id="custom", name="Other")
    assert second.status == "error"
    assert any(d.get("code") == "1CE001" for d in second.diagnostics)


def test_cli_extension_add(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    _init_config_project(target)
    monkeypatch.chdir(target)
    result = runner.invoke(
        app,
        [
            "extension",
            "add",
            "--id",
            "tests",
            "--name",
            "Tests",
            "--purpose",
            "tests",
            "--output",
            "json",
        ],
    )
    assert result.exit_code == SUCCESS, result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert (target / "src" / "cfe" / "tests" / "Configuration.xml").is_file()


def test_cli_extension_add_no_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["extension", "add", "--id", "x", "--output", "json"])
    assert result.exit_code == PROJECT_ERROR


def test_add_extension_from_cfe(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    _init_config_project(target)
    cfe = tmp_path / "CustomExt.cfe"
    cfe.write_bytes(b"CFE")
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")

    def fake_import(
        _ibcmd: Path,
        *,
        db_path: Path,
        data_path: Path,
        cfe_path: Path,
        source_dir: Path,
        extension: str,
        run: Any = None,
    ) -> list[str]:
        assert cfe_path == cfe.resolve()
        assert extension == "CustomExt"
        source_dir.mkdir(parents=True, exist_ok=True)
        (source_dir / "Configuration.xml").write_text(
            '<?xml version="1.0"?><MetaDataObject/>',
            encoding="utf-8",
        )
        return ["create", "load:CustomExt", "apply:CustomExt", "export"]

    result = add_extension(
        target,
        from_cfe=cfe,
        name="CustomExt",
        purpose="product",
        discover=lambda: _fake_discovery(ibcmd=ibcmd),
        import_cfe_fn=fake_import,
    )
    assert result.status == "ok", result.diagnostics
    data = yaml.safe_load(
        (target / ".1c-dev" / "project.yaml").read_text(encoding="utf-8")
    )
    exts = data["configurations"][0]["extensions"]
    assert len(exts) == 1
    assert exts[0]["id"] == "CustomExt"
    assert exts[0]["name"] == "CustomExt"
    assert exts[0]["source"] == {"format": "xml", "path": "src/cfe/CustomExt"}
    assert (target / "src" / "cfe" / "CustomExt" / "Configuration.xml").is_file()
    assert not (target / "src" / "cfe" / "CustomExt.cfe").exists()


def test_add_extension_from_cfe_needs_ibcmd(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    _init_config_project(target)
    cfe = tmp_path / "CustomExt.cfe"
    cfe.write_bytes(b"CFE")
    result = add_extension(
        target,
        from_cfe=cfe,
        name="CustomExt",
        discover=lambda: _fake_discovery(ibcmd=None),
        import_cfe_fn=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no call")),
    )
    assert result.status == "error"
    assert any(d.get("code") == "1CE004" for d in result.diagnostics)


def test_cli_extension_add_from_cfe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    _init_config_project(target)
    cfe = tmp_path / "Ext.cfe"
    cfe.write_bytes(b"CFE")
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")

    def fake_import(
        _ibcmd: Path,
        *,
        db_path: Path,
        data_path: Path,
        cfe_path: Path,
        source_dir: Path,
        extension: str,
        run: Any = None,
    ) -> list[str]:
        source_dir.mkdir(parents=True, exist_ok=True)
        (source_dir / "Configuration.xml").write_text("<MetaDataObject/>", encoding="utf-8")
        return ["create", "load:Ext", "apply:Ext", "export"]

    monkeypatch.setattr(
        "core.extension.add.discover_environment",
        lambda: _fake_discovery(ibcmd=ibcmd),
    )
    monkeypatch.setattr("core.extension.add.import_cfe_with_ibcmd", fake_import)
    monkeypatch.chdir(target)
    result = runner.invoke(
        app,
        [
            "extension",
            "add",
            "--from",
            str(cfe),
            "--name",
            "Ext",
            "--output",
            "json",
        ],
    )
    assert result.exit_code == SUCCESS, result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert (target / "src" / "cfe" / "Ext" / "Configuration.xml").is_file()


def test_run_extension_list_ok(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    _init_config_project(target)
    ib_dir = target / ".1c-dev" / "runtime" / "main"
    ib_dir.mkdir(parents=True, exist_ok=True)
    (ib_dir / IB_MARKER).write_bytes(b"")
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")

    def run(argv: list[str]) -> IbcmdRunResult:
        return IbcmdRunResult(
            returncode=0,
            stdout="Name\nCustomExt\n",
            stderr="",
            argv=argv,
        )

    result = run_extension_list(
        target,
        discover=lambda: _fake_discovery(ibcmd=ibcmd),
        run=run,
    )
    assert result.status == "ok"
    assert [e.name for e in result.extensions] == ["CustomExt"]


def test_run_extension_list_missing_ib(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    _init_config_project(target)
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    result = run_extension_list(
        target,
        discover=lambda: _fake_discovery(ibcmd=ibcmd),
    )
    assert result.status == "error"
    assert any(d.get("code") == "1CE010" for d in result.diagnostics)


def test_cli_extension_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    _init_config_project(target)
    ib_dir = target / ".1c-dev" / "runtime" / "main"
    ib_dir.mkdir(parents=True, exist_ok=True)
    (ib_dir / IB_MARKER).write_bytes(b"")
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    monkeypatch.chdir(target)
    monkeypatch.setattr(
        "core.extension.list.discover_environment",
        lambda: _fake_discovery(ibcmd=ibcmd),
    )

    def fake_list(*_a: Any, **_k: Any) -> tuple[IbcmdRunResult, list[Any]]:
        from adapters.platform_ibcmd.client import ExtensionInfo

        return (
            IbcmdRunResult(returncode=0, stdout="X\n", stderr="", argv=[]),
            [ExtensionInfo(name="X")],
        )

    monkeypatch.setattr("core.extension.list.list_extensions", fake_list)
    result = runner.invoke(app, ["extension", "list", "--output", "json"])
    assert result.exit_code == SUCCESS, result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["extensions"][0]["name"] == "X"
