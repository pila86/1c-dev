"""Tests for extension add / list (ADR-023 / #88 / #163)."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from adapters.edtcli import EdtCliInfo, EdtCliRunResult
from adapters.platform.discovery import DiscoveryResult, PlatformInfo, ToolInfo
from adapters.platform_ibcmd.client import IbcmdRunResult
from adapters.platform_ibcmd.constants import IB_MARKER
from adapters.source.edt.constants import CONFIGURATION_MDO_REL, PROJECT_FILE_NAME
from cli.main import app
from core.exit_codes import PROJECT_ERROR, SUCCESS
from core.extension import add_extension, run_extension_list
from core.extension.add import CODE_EXT_FORMAT
from core.project import init_project
from core.source.result import ConvertResult

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
    assert exts[0]["source"] == {"format": "xml", "path": "src/cfe/custom"}


def _fake_edt_import(argv: list[str]) -> EdtCliRunResult:
    project = Path(argv[argv.index("--project") + 1])
    project.mkdir(parents=True, exist_ok=True)
    (project / PROJECT_FILE_NAME).write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<projectDescription><name>CustomExt</name>"
        "<natures><nature>com._1c.g5.v8.dt.core.V8ConfigurationNature</nature>"
        "</natures></projectDescription>\n",
        encoding="utf-8",
    )
    (project / "DT-INF").mkdir(exist_ok=True)
    (project / "DT-INF" / "PROJECT.PMF").write_text(
        "Manifest-Version: 1.0\nRuntime-Version: 8.3.24\n",
        encoding="utf-8",
    )
    mdo = project / CONFIGURATION_MDO_REL
    mdo.parent.mkdir(parents=True, exist_ok=True)
    mdo.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<mdclass:Configuration xmlns:mdclass="http://g5.1c.ru/v8/dt/md">'
        "<name>CustomExt</name></mdclass:Configuration>\n",
        encoding="utf-8",
    )
    return EdtCliRunResult(returncode=0, stdout="imported", stderr="", argv=argv)


def _fake_edt_run(argv: list[str]) -> EdtCliRunResult:
    if "import" in argv:
        return _fake_edt_import(argv)
    return EdtCliRunResult(returncode=0, stdout="ok", stderr="", argv=argv)


def _edtcli_discover(tmp_path: Path) -> Callable[[], EdtCliInfo]:
    cli = tmp_path / "1cedtcli"
    cli.write_text("#!/bin/sh\n", encoding="utf-8")
    return lambda: EdtCliInfo(found=True, path=cli, version="2025.1.0")


def test_add_extension_format_edt(tmp_path: Path) -> None:
    """#163: format=edt → XML scaffold then convert; manifest format edt."""
    target = tmp_path / "shop"
    target.mkdir()
    _init_config_project(target)

    result = add_extension(
        target,
        ext_id="custom",
        name="CustomExt",
        purpose="product",
        format="edt",
        edt_run=_fake_edt_run,
        edt_discover=_edtcli_discover(tmp_path),
    )
    assert result.status == "ok", result.diagnostics

    ext = target / "src" / "cfe" / "custom"
    assert (ext / PROJECT_FILE_NAME).is_file()
    assert (ext / CONFIGURATION_MDO_REL).is_file()
    assert not (ext / "Configuration.xml").exists()

    data = yaml.safe_load(
        (target / ".1c-dev" / "project.yaml").read_text(encoding="utf-8")
    )
    exts = data["configurations"][0]["extensions"]
    assert len(exts) == 1
    assert exts[0]["source"] == {"format": "edt", "path": "src/cfe/custom"}


def test_add_extension_from_cfe_format_edt(tmp_path: Path) -> None:
    """#163: --from .cfe + format=edt → export XML then convert."""
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
        del db_path, data_path, run
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
        format="edt",
        discover=lambda: _fake_discovery(ibcmd=ibcmd),
        import_cfe_fn=fake_import,
        edt_run=_fake_edt_run,
        edt_discover=_edtcli_discover(tmp_path),
    )
    assert result.status == "ok", result.diagnostics
    data = yaml.safe_load(
        (target / ".1c-dev" / "project.yaml").read_text(encoding="utf-8")
    )
    exts = data["configurations"][0]["extensions"]
    assert exts[0]["source"] == {"format": "edt", "path": "src/cfe/CustomExt"}
    ext = target / "src" / "cfe" / "CustomExt"
    assert (ext / PROJECT_FILE_NAME).is_file()
    assert not (ext / "Configuration.xml").exists()


def test_add_extension_invalid_format(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    _init_config_project(target)
    result = add_extension(target, ext_id="custom", format="cf")
    assert result.status == "error"
    assert any(d.get("code") == CODE_EXT_FORMAT for d in result.diagnostics)


def test_cli_extension_add_format_edt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    _init_config_project(target)
    monkeypatch.chdir(target)
    monkeypatch.setattr("core.extension.add.run_convert", _fake_run_convert_edt)
    result = runner.invoke(
        app,
        [
            "extension",
            "add",
            "--id",
            "custom",
            "--name",
            "CustomExt",
            "--format",
            "edt",
            "--output",
            "json",
        ],
    )
    assert result.exit_code == SUCCESS, result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    data = yaml.safe_load(
        (target / ".1c-dev" / "project.yaml").read_text(encoding="utf-8")
    )
    assert data["configurations"][0]["extensions"][0]["source"]["format"] == "edt"


def _fake_run_convert_edt(*_a: Any, **kwargs: Any) -> ConvertResult:
    """Minimal convert mock: rewrite extension source to edt layout in place."""
    start = Path(_a[0] if _a else kwargs.get("start") or Path.cwd()).resolve()
    extension_id = str(kwargs.get("extension_id") or "custom")
    manifest = start / ".1c-dev" / "project.yaml"
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    for conf in data["configurations"]:
        for ext in conf.get("extensions") or []:
            if ext.get("id") == extension_id:
                path_rel = ext["source"]["path"]
                ext["source"]["format"] = "edt"
                ext_dir = start / path_rel
                for child in list(ext_dir.iterdir()):
                    if child.is_file():
                        child.unlink()
                    elif child.is_dir():
                        shutil.rmtree(child)
                (ext_dir / PROJECT_FILE_NAME).write_text(
                    "<projectDescription/>", encoding="utf-8"
                )
                mdo = ext_dir / CONFIGURATION_MDO_REL
                mdo.parent.mkdir(parents=True, exist_ok=True)
                mdo.write_text("<mdclass:Configuration/>", encoding="utf-8")
                break
    manifest.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return ConvertResult(
        status="ok",
        root=start,
        extension_id=extension_id,
        from_format="xml",
        to_format="edt",
        source_rel=f"src/cfe/{extension_id}",
        steps=["edt-import"],
    )


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
