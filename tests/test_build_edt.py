"""build / check for source.format: edt (#155 / #161)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from adapters.edtcli import (
    CODE_EDTCLI_COLLISION,
    CODE_EDTCLI_EMPTY_EXPORT,
    CODE_EDTCLI_MISSING,
    EDTCLI_SKIP_MESSAGE,
    PLATFORM_SKIP_MESSAGE,
    EdtCliInfo,
    EdtCliRunResult,
    discover_edtcli,
)
from adapters.platform.discovery import DiscoveryResult, PlatformInfo, ToolInfo
from adapters.platform_ibcmd.client import IbcmdRunResult
from adapters.platform_ibcmd.constants import IB_MARKER
from adapters.source.edt.constants import CODE_LAYOUT_NOT_EDT
from cli.main import app
from core.build import BuildResult, run_build
from core.check import run_check
from core.exit_codes import ENV_UNAVAILABLE, RUNTIME_FAILURE
from core.project.constants import HOME_EXPORT_DIR_NAME
from tests.helpers_project import bootstrap_configuration_project

runner = CliRunner()
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "edt_spike"


def _copy_edt_fixture(tmp_path: Path) -> Path:
    target = tmp_path / "edt_proj"
    shutil.copytree(FIXTURE, target)
    return target


def _write_minimal_edt_root(path: Path, *, name: str = "CustomExt") -> None:
    """Minimal EDT project root (``.project`` + Configuration.mdo)."""
    path.mkdir(parents=True, exist_ok=True)
    (path / ".project").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<projectDescription>\n"
        f"\t<name>{name}</name>\n"
        "\t<natures>\n"
        "\t\t<nature>com._1c.g5.v8.dt.core.V8ConfigurationNature</nature>\n"
        "\t</natures>\n"
        "</projectDescription>\n",
        encoding="utf-8",
    )
    mdo = path / "src" / "Configuration" / "Configuration.mdo"
    mdo.parent.mkdir(parents=True, exist_ok=True)
    mdo.write_text('<?xml version="1.0"?>\n<Configuration/>\n', encoding="utf-8")


def _add_nested_extension(
    root: Path,
    *,
    ext_id: str = "custom",
    name: str = "CustomExt",
    fmt: str = "edt",
    path: str = "src/cfe/custom",
) -> None:
    manifest_path = root / ".1c-dev" / "project.yaml"
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    data["configurations"][0]["extensions"] = [
        {
            "id": ext_id,
            "name": name,
            "purpose": "product",
            "source": {"format": fmt, "path": path},
        }
    ]
    manifest_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _fake_discovery(*, ibcmd: Path | None, onecv8: Path | None = None) -> DiscoveryResult:
    return DiscoveryResult(
        platform=PlatformInfo(found=True, version="8.3.25.1560", path=Path("/opt/1cv8")),
        ibcmd=ToolInfo(found=ibcmd is not None, path=ibcmd),
        onecv8=ToolInfo(found=onecv8 is not None, path=onecv8),
        onecv8c=ToolInfo(found=False, path=None),
        ibsrv=ToolInfo(found=False, path=None),
        webinst=ToolInfo(found=False, path=None),
    )


def _ok_ibcmd(argv: list[str]) -> IbcmdRunResult:
    if "create" in argv:
        for arg in argv:
            if arg.startswith("--db-path="):
                db_path = Path(arg.split("=", 1)[1])
                db_path.mkdir(parents=True, exist_ok=True)
                (db_path / IB_MARKER).write_bytes(b"")
                break
    return IbcmdRunResult(returncode=0, stdout="ok", stderr="", argv=argv)


def _fake_edt_export(argv: list[str]) -> EdtCliRunResult:
    out = Path(argv[argv.index("--configuration-files") + 1])
    out.mkdir(parents=True, exist_ok=True)
    (out / "Configuration.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<MetaDataObject version="2.17">\n'
        "<ChildObjects><Catalog>Products</Catalog></ChildObjects>\n"
        "</MetaDataObject>\n",
        encoding="utf-8",
    )
    (out / "Catalogs").mkdir(exist_ok=True)
    (out / "Catalogs" / "Products.xml").write_text("<Catalog/>\n", encoding="utf-8")
    return EdtCliRunResult(returncode=0, stdout="exported", stderr="", argv=argv)


def test_run_build_edt_mock(tmp_path: Path) -> None:
    target = _copy_edt_fixture(tmp_path)
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    edtcli = tmp_path / "1cedtcli"
    edtcli.write_text("", encoding="utf-8")
    captured_source: list[Path] = []

    def build_fn(
        _ibcmd: Path,
        *,
        db_path: Path,
        data_path: Path,
        source_dir: Path,
        cf_path: Path | None = None,
        primary_extension: str | None = None,
        extensions: list | None = None,
        run=None,
    ) -> list[str]:
        del db_path, data_path, cf_path, primary_extension, extensions, run
        captured_source.append(source_dir)
        return ["create", "import", "apply"]

    result = run_build(
        target,
        discover=lambda: _fake_discovery(ibcmd=ibcmd),
        build_fn=build_fn,
        edt_run=_fake_edt_export,
        edt_discover=lambda: EdtCliInfo(
            found=True, path=edtcli, version="2026.2.2+21"
        ),
    )
    assert result.status == "ok", result.to_payload()
    assert result.steps == ["edt-export", "create", "import", "apply"]
    export_dir = target / HOME_EXPORT_DIR_NAME / "main"
    assert export_dir.is_dir()
    assert (export_dir / "Configuration.xml").is_file()
    assert captured_source == [export_dir.resolve()]


def test_run_build_edt_missing_cli(tmp_path: Path) -> None:
    target = _copy_edt_fixture(tmp_path)
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    result = run_build(
        target,
        discover=lambda: _fake_discovery(ibcmd=ibcmd),
        edt_discover=lambda: EdtCliInfo(found=False),
    )
    assert result.status == "failed"
    assert any(d.get("code") == CODE_EDTCLI_MISSING for d in result.diagnostics)


def test_cli_build_edt_env_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _copy_edt_fixture(tmp_path)
    monkeypatch.chdir(target)
    monkeypatch.setattr(
        "adapters.edtcli.client.discover_edtcli",
        lambda **_kwargs: EdtCliInfo(found=False),
    )
    result = runner.invoke(app, ["build", "--output", "json"])
    assert result.exit_code == ENV_UNAVAILABLE
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert any(d.get("code") == CODE_EDTCLI_MISSING for d in payload["diagnostics"])


def test_cli_build_1cs006_exit_runtime_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-032: 1CS006 (workspace collision) → RUNTIME_FAILURE (4), не 6."""
    target = _copy_edt_fixture(tmp_path)
    monkeypatch.chdir(target)

    def fake_build(*_a: object, **_k: object) -> BuildResult:
        return BuildResult(
            status="failed",
            diagnostics=[
                {
                    "severity": "error",
                    "code": CODE_EDTCLI_COLLISION,
                    "message": "проект уже существует в workspace",
                    "source": "edt",
                }
            ],
        )

    monkeypatch.setattr("cli.build.run_build", fake_build)
    result = runner.invoke(app, ["build", "--output", "json"])
    assert result.exit_code == RUNTIME_FAILURE


def test_run_build_edt_then_check_mock(tmp_path: Path) -> None:
    """check remains IB-only: after mocked EDT build, check sees the IB."""
    target = _copy_edt_fixture(tmp_path)
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    onecv8 = tmp_path / "1cv8"
    onecv8.write_text("", encoding="utf-8")
    edtcli = tmp_path / "1cedtcli"
    edtcli.write_text("", encoding="utf-8")

    build = run_build(
        target,
        discover=lambda: _fake_discovery(ibcmd=ibcmd, onecv8=onecv8),
        run=_ok_ibcmd,
        edt_run=_fake_edt_export,
        edt_discover=lambda: EdtCliInfo(
            found=True, path=edtcli, version="2026.2.2+21"
        ),
    )
    assert build.status == "ok", build.to_payload()
    assert (target / ".1c-dev" / "runtime" / "main" / IB_MARKER).is_file()

    check = run_check(
        target,
        discover=lambda: _fake_discovery(ibcmd=ibcmd, onecv8=onecv8),
        run=_ok_ibcmd,
        check_fn=lambda *_a, **_k: None,
        modules_fn=lambda *_a, **_k: None,
    )
    assert check.status == "ok", check.to_payload()
    assert check.steps == ["metadata", "modules"]


@pytest.mark.integration
def test_edt_build_check_integration(tmp_path: Path) -> None:
    """Live 1cedtcli export + ibcmd build + check on edt_spike copy."""
    edt = discover_edtcli()
    if not edt.found or edt.path is None:
        pytest.skip(EDTCLI_SKIP_MESSAGE)

    from adapters.platform import discover_environment

    discovery = discover_environment()
    if not discovery.ibcmd.found or discovery.ibcmd.path is None:
        pytest.skip(PLATFORM_SKIP_MESSAGE)
    if not discovery.onecv8.found or discovery.onecv8.path is None:
        pytest.skip(PLATFORM_SKIP_MESSAGE)

    target = _copy_edt_fixture(tmp_path)
    build = run_build(target)
    assert build.status == "ok", build.to_payload()
    assert "edt-export" in build.steps
    assert "import" in build.steps
    export_xml = target / HOME_EXPORT_DIR_NAME / "main" / "Configuration.xml"
    assert export_xml.is_file() and export_xml.stat().st_size > 0

    check = run_check(target)
    assert "metadata" in check.steps
    # Metadata check is format-agnostic on the loaded IB; must succeed after EDT build.
    meta_errors = [
        d
        for d in check.diagnostics
        if d.get("severity") == "error" and "CheckModules" not in str(d.get("message", ""))
    ]
    assert not meta_errors, check.to_payload()
    # /CheckModules needs working Designer GUI (DISPLAY/X11); rc 255 is env, not EDT.
    modules_errors = [
        d
        for d in check.diagnostics
        if d.get("severity") == "error" and "CheckModules" in str(d.get("message", ""))
    ]
    if modules_errors:
        pytest.skip(
            "Designer /CheckModules недоступен в окружении (часто DISPLAY/Wayland); "
            "EDT build + ibcmd metadata check OK"
        )
    assert check.status == "ok", check.to_payload()


# --- nested extensions[].source.format: edt (#161) ---


def test_run_build_config_edt_extension_edt_mock(tmp_path: Path) -> None:
    """Config edt + nested extension edt → separate staging under export/.../ext/."""
    target = _copy_edt_fixture(tmp_path)
    _write_minimal_edt_root(target / "src" / "cfe" / "custom", name="CustomExt")
    _add_nested_extension(target)

    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    edtcli = tmp_path / "1cedtcli"
    edtcli.write_text("", encoding="utf-8")
    captured_ext: list[Path] = []

    def build_fn(
        _ibcmd: Path,
        *,
        db_path: Path,
        data_path: Path,
        source_dir: Path,
        cf_path: Path | None = None,
        primary_extension: str | None = None,
        extensions: list | None = None,
        run=None,
    ) -> list[str]:
        del db_path, data_path, source_dir, cf_path, primary_extension, run
        assert extensions is not None and len(extensions) == 1
        name, path, kind = extensions[0]
        assert name == "CustomExt"
        assert kind == "xml"
        captured_ext.append(path)
        return ["create", "import", "apply", "import:CustomExt", "apply:CustomExt"]

    result = run_build(
        target,
        discover=lambda: _fake_discovery(ibcmd=ibcmd),
        build_fn=build_fn,
        edt_run=_fake_edt_export,
        edt_discover=lambda: EdtCliInfo(
            found=True, path=edtcli, version="2026.2.2+21"
        ),
    )
    assert result.status == "ok", result.to_payload()
    assert result.steps == [
        "edt-export",
        "edt-export:CustomExt",
        "create",
        "import",
        "apply",
        "import:CustomExt",
        "apply:CustomExt",
    ]
    ext_export = target / HOME_EXPORT_DIR_NAME / "main" / "ext" / "custom"
    assert ext_export.is_dir()
    assert (ext_export / "Configuration.xml").is_file()
    assert (target / HOME_EXPORT_DIR_NAME / "main" / "Configuration.xml").is_file()
    assert captured_ext == [ext_export.resolve()]


def test_run_build_config_edt_extension_xml_mock(tmp_path: Path) -> None:
    """Config edt + nested extension xml — mixed mode, no second edt-export."""
    target = _copy_edt_fixture(tmp_path)
    ext_dir = target / "src" / "cfe" / "custom"
    ext_dir.mkdir(parents=True)
    (ext_dir / "Configuration.xml").write_text(
        '<?xml version="1.0"?><MetaDataObject><ChildObjects/></MetaDataObject>',
        encoding="utf-8",
    )
    _add_nested_extension(target, fmt="xml", path="src/cfe/custom")

    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    edtcli = tmp_path / "1cedtcli"
    edtcli.write_text("", encoding="utf-8")
    captured_ext: list[Path] = []

    def build_fn(
        _ibcmd: Path,
        *,
        db_path: Path,
        data_path: Path,
        source_dir: Path,
        cf_path: Path | None = None,
        primary_extension: str | None = None,
        extensions: list | None = None,
        run=None,
    ) -> list[str]:
        del db_path, data_path, source_dir, cf_path, primary_extension, run
        assert extensions is not None and len(extensions) == 1
        name, path, kind = extensions[0]
        assert name == "CustomExt" and kind == "xml"
        captured_ext.append(path)
        return ["create", "import", "apply", "import:CustomExt", "apply:CustomExt"]

    result = run_build(
        target,
        discover=lambda: _fake_discovery(ibcmd=ibcmd),
        build_fn=build_fn,
        edt_run=_fake_edt_export,
        edt_discover=lambda: EdtCliInfo(
            found=True, path=edtcli, version="2026.2.2+21"
        ),
    )
    assert result.status == "ok", result.to_payload()
    assert result.steps == [
        "edt-export",
        "create",
        "import",
        "apply",
        "import:CustomExt",
        "apply:CustomExt",
    ]
    assert "edt-export:CustomExt" not in result.steps
    assert captured_ext == [ext_dir.resolve()]


def test_run_build_config_xml_extension_edt_mock(tmp_path: Path) -> None:
    """Config xml + nested extension edt — export only under export/<id>/ext/."""
    target = tmp_path / "shop"
    target.mkdir()
    assert bootstrap_configuration_project(target, name="Shop").status == "ok"
    _write_minimal_edt_root(target / "src" / "cfe" / "custom", name="CustomExt")
    _add_nested_extension(target)

    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    edtcli = tmp_path / "1cedtcli"
    edtcli.write_text("", encoding="utf-8")
    captured_ext: list[Path] = []

    def build_fn(
        _ibcmd: Path,
        *,
        db_path: Path,
        data_path: Path,
        source_dir: Path,
        cf_path: Path | None = None,
        primary_extension: str | None = None,
        extensions: list | None = None,
        run=None,
    ) -> list[str]:
        del db_path, data_path, source_dir, cf_path, primary_extension, run
        assert extensions is not None and len(extensions) == 1
        name, path, kind = extensions[0]
        assert name == "CustomExt" and kind == "xml"
        captured_ext.append(path)
        return ["create", "import", "apply", "import:CustomExt", "apply:CustomExt"]

    result = run_build(
        target,
        discover=lambda: _fake_discovery(ibcmd=ibcmd),
        build_fn=build_fn,
        edt_run=_fake_edt_export,
        edt_discover=lambda: EdtCliInfo(
            found=True, path=edtcli, version="2026.2.2+21"
        ),
    )
    assert result.status == "ok", result.to_payload()
    assert result.steps == [
        "edt-export:CustomExt",
        "create",
        "import",
        "apply",
        "import:CustomExt",
        "apply:CustomExt",
    ]
    ext_export = target / HOME_EXPORT_DIR_NAME / "main" / "ext" / "custom"
    assert (ext_export / "Configuration.xml").is_file()
    assert captured_ext == [ext_export.resolve()]


def test_run_build_extension_edt_bad_layout(tmp_path: Path) -> None:
    """Non-EDT directory with format: edt → 1CS003, no silent ibcmd."""
    target = _copy_edt_fixture(tmp_path)
    bad = target / "src" / "cfe" / "custom"
    bad.mkdir(parents=True)
    (bad / "readme.txt").write_text("not edt\n", encoding="utf-8")
    _add_nested_extension(target)

    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    edtcli = tmp_path / "1cedtcli"
    edtcli.write_text("", encoding="utf-8")

    result = run_build(
        target,
        discover=lambda: _fake_discovery(ibcmd=ibcmd),
        edt_run=_fake_edt_export,
        edt_discover=lambda: EdtCliInfo(
            found=True, path=edtcli, version="2026.2.2+21"
        ),
    )
    assert result.status == "failed"
    assert any(d.get("code") == CODE_LAYOUT_NOT_EDT for d in result.diagnostics)
    assert "edt-export:CustomExt" not in result.steps


def test_run_build_extension_edt_empty_export(tmp_path: Path) -> None:
    """Empty 1cedtcli export for nested extension → 1CS007."""
    target = _copy_edt_fixture(tmp_path)
    _write_minimal_edt_root(target / "src" / "cfe" / "custom", name="CustomExt")
    _add_nested_extension(target)

    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    edtcli = tmp_path / "1cedtcli"
    edtcli.write_text("", encoding="utf-8")

    def empty_or_ok(argv: list[str]) -> EdtCliRunResult:
        out = Path(argv[argv.index("--configuration-files") + 1])
        out.mkdir(parents=True, exist_ok=True)
        # Main config gets valid XML; extension staging is left empty.
        if "ext" in out.parts:
            return EdtCliRunResult(returncode=0, stdout="", stderr="", argv=argv)
        return _fake_edt_export(argv)

    result = run_build(
        target,
        discover=lambda: _fake_discovery(ibcmd=ibcmd),
        edt_run=empty_or_ok,
        edt_discover=lambda: EdtCliInfo(
            found=True, path=edtcli, version="2026.2.2+21"
        ),
    )
    assert result.status == "failed"
    assert any(d.get("code") == CODE_EDTCLI_EMPTY_EXPORT for d in result.diagnostics)


@pytest.mark.integration
def test_nested_extension_edt_build_integration(tmp_path: Path) -> None:
    """Live: scaffold XML extension → 1cedtcli import to EDT → build (#161)."""
    from adapters.edtcli import import_configuration, require_edtcli
    from adapters.platform import discover_environment
    from core.extension import add_extension

    edt = discover_edtcli()
    if not edt.found or edt.path is None:
        pytest.skip(EDTCLI_SKIP_MESSAGE)

    discovery = discover_environment()
    if not discovery.ibcmd.found or discovery.ibcmd.path is None:
        pytest.skip(PLATFORM_SKIP_MESSAGE)

    target = tmp_path / "shop"
    target.mkdir()
    assert bootstrap_configuration_project(target, name="Shop").status == "ok"
    assert add_extension(
        target, ext_id="custom", name="CustomExt", purpose="product"
    ).status == "ok"

    xml_src = target / "src" / "cfe" / "custom"
    edt_src = target / "src" / "cfe" / "custom_edt"
    info = require_edtcli(info=edt)
    assert info.path is not None
    import_configuration(
        info.path,
        configuration_files=xml_src,
        project=edt_src,
    )
    assert (edt_src / ".project").is_file()
    assert (edt_src / "src" / "Configuration" / "Configuration.mdo").is_file()

    _add_nested_extension(target, path="src/cfe/custom_edt", fmt="edt")

    build = run_build(target)
    assert build.status == "ok", build.to_payload()
    assert "edt-export:CustomExt" in build.steps
    assert "import:CustomExt" in build.steps
    assert "apply:CustomExt" in build.steps
    ext_xml = (
        target / HOME_EXPORT_DIR_NAME / "main" / "ext" / "custom" / "Configuration.xml"
    )
    assert ext_xml.is_file() and ext_xml.stat().st_size > 0


@pytest.mark.integration
def test_config_edt_extension_xml_build_integration(tmp_path: Path) -> None:
    """Live: config edt + nested extension xml (mixed mode)."""
    from adapters.platform import discover_environment
    from core.extension import add_extension

    edt = discover_edtcli()
    if not edt.found or edt.path is None:
        pytest.skip(EDTCLI_SKIP_MESSAGE)

    discovery = discover_environment()
    if not discovery.ibcmd.found or discovery.ibcmd.path is None:
        pytest.skip(PLATFORM_SKIP_MESSAGE)

    target = _copy_edt_fixture(tmp_path)
    assert add_extension(
        target, ext_id="custom", name="CustomExt", purpose="product"
    ).status == "ok"

    build = run_build(target)
    assert build.status == "ok", build.to_payload()
    assert "edt-export" in build.steps
    assert "edt-export:CustomExt" not in build.steps
    assert "import:CustomExt" in build.steps
    assert "apply:CustomExt" in build.steps
