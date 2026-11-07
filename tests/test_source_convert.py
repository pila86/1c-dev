"""source.convert XML ↔ EDT + manifest (#156)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from adapters.edtcli import (
    CODE_CONVERT_DIRTY,
    CODE_EDTCLI_MISSING,
    EDTCLI_SKIP_MESSAGE,
    EdtCliInfo,
    EdtCliRunResult,
    discover_edtcli,
)
from adapters.source.edt.constants import CONFIGURATION_MDO_REL, PROJECT_FILE_NAME
from cli.main import app
from core.exit_codes import ENV_UNAVAILABLE, PROJECT_ERROR, SUCCESS
from core.source import run_convert

runner = CliRunner()
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "edt_spike"


def _copy_edt_fixture(tmp_path: Path) -> Path:
    target = tmp_path / "edt_proj"
    shutil.copytree(FIXTURE, target)
    return target


def _write_xml_project(tmp_path: Path) -> Path:
    """Minimal schema-2 project with Designer XML source (Products catalog)."""
    root = tmp_path / "xml_proj"
    root.mkdir()
    source = root / "src" / "cf"
    source.mkdir(parents=True)
    (source / "Configuration.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" version="2.17">\n'
        "  <Configuration>\n"
        "    <ChildObjects>\n"
        "      <Language>Русский</Language>\n"
        "      <Catalog>Products</Catalog>\n"
        "    </ChildObjects>\n"
        "  </Configuration>\n"
        "</MetaDataObject>\n",
        encoding="utf-8",
    )
    (source / "Catalogs").mkdir()
    (source / "Catalogs" / "Products.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<MetaDataObject/>\n',
        encoding="utf-8",
    )
    (source / "Languages").mkdir()
    (source / "Languages" / "Русский.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<MetaDataObject/>\n',
        encoding="utf-8",
    )
    home = root / ".1c-dev"
    home.mkdir()
    (home / "project.yaml").write_text(
        yaml.safe_dump(
            {
                "schema": "2",
                "project": {"name": "XmlSpike", "type": "configuration"},
                "platform": {"version": "8.5.1"},
                "configurations": [
                    {
                        "id": "main",
                        "type": "configuration",
                        "source": {"format": "xml", "path": "src/cf"},
                        "default": True,
                    }
                ],
                "runtimes": [
                    {
                        "id": "main",
                        "configuration": "main",
                        "type": "file",
                        "path": ".1c-dev/runtime/main",
                        "default": True,
                    }
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return root


def _fake_import(argv: list[str]) -> EdtCliRunResult:
    project = Path(argv[argv.index("--project") + 1])
    project.mkdir(parents=True, exist_ok=True)
    (project / PROJECT_FILE_NAME).write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<projectDescription><name>Converted</name>"
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
        "<name>Converted</name></mdclass:Configuration>\n",
        encoding="utf-8",
    )
    catalogs = project / "src" / "Catalogs" / "Products"
    catalogs.mkdir(parents=True, exist_ok=True)
    (catalogs / "Products.mdo").write_text("<mdclass:Catalog/>\n", encoding="utf-8")
    return EdtCliRunResult(returncode=0, stdout="imported", stderr="", argv=argv)


def _fake_export(argv: list[str]) -> EdtCliRunResult:
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


def _fake_edt_run(argv: list[str]) -> EdtCliRunResult:
    if "import" in argv:
        return _fake_import(argv)
    return _fake_export(argv)


def _read_format(root: Path) -> tuple[str, str]:
    data = yaml.safe_load((root / ".1c-dev" / "project.yaml").read_text(encoding="utf-8"))
    source = data["configurations"][0]["source"]
    return str(source["format"]), str(source["path"])


def _read_extension_format(root: Path, ext_id: str = "tests") -> tuple[str, str]:
    data = yaml.safe_load((root / ".1c-dev" / "project.yaml").read_text(encoding="utf-8"))
    for ext in data["configurations"][0]["extensions"]:
        if ext["id"] == ext_id:
            source = ext["source"]
            return str(source["format"]), str(source["path"])
    raise AssertionError(f"extension {ext_id!r} not in manifest")


def _write_xml_project_with_extension(tmp_path: Path) -> Path:
    """XML config + nested XML extension under src/cfe/tests (#162)."""
    root = _write_xml_project(tmp_path)
    ext_source = root / "src" / "cfe" / "tests"
    ext_source.mkdir(parents=True)
    (ext_source / "Configuration.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" version="2.17">\n'
        "  <Configuration>\n"
        "    <ChildObjects>\n"
        "      <Language>Русский</Language>\n"
        "      <CommonModule>ОМ_Тесты</CommonModule>\n"
        "    </ChildObjects>\n"
        "  </Configuration>\n"
        "</MetaDataObject>\n",
        encoding="utf-8",
    )
    (ext_source / "CommonModules").mkdir()
    (ext_source / "CommonModules" / "ОМ_Тесты.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<MetaDataObject/>\n',
        encoding="utf-8",
    )
    (ext_source / "Languages").mkdir()
    (ext_source / "Languages" / "Русский.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<MetaDataObject/>\n',
        encoding="utf-8",
    )
    manifest = root / ".1c-dev" / "project.yaml"
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    data["configurations"][0]["extensions"] = [
        {
            "id": "tests",
            "name": "Tests",
            "purpose": "tests",
            "source": {"format": "xml", "path": "src/cfe/tests"},
        }
    ]
    manifest.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return root


def _edtcli_discover(tmp_path: Path):
    edtcli = tmp_path / "1cedtcli"
    edtcli.write_text("", encoding="utf-8")
    return lambda: EdtCliInfo(found=True, path=edtcli, version="2026.2.2+21")


def test_convert_xml_to_edt_mock(tmp_path: Path) -> None:
    root = _write_xml_project(tmp_path)
    edtcli = tmp_path / "1cedtcli"
    edtcli.write_text("", encoding="utf-8")

    result = run_convert(
        root,
        to="edt",
        edt_run=_fake_edt_run,
        edt_discover=lambda: EdtCliInfo(found=True, path=edtcli, version="2026.2.2+21"),
    )
    assert result.status == "ok", result.diagnostics
    assert result.from_format == "xml"
    assert result.to_format == "edt"
    assert "edt-import" in result.steps
    assert "update-manifest" in result.steps

    fmt, path = _read_format(root)
    assert fmt == "edt"
    assert path == "src/cf"
    source = root / "src" / "cf"
    assert (source / PROJECT_FILE_NAME).is_file()
    assert (source / CONFIGURATION_MDO_REL).is_file()
    assert not (source / "Configuration.xml").exists()


def test_convert_edt_to_xml_mock(tmp_path: Path) -> None:
    root = _copy_edt_fixture(tmp_path)
    edtcli = tmp_path / "1cedtcli"
    edtcli.write_text("", encoding="utf-8")

    result = run_convert(
        root,
        to="xml",
        edt_run=_fake_edt_run,
        edt_discover=lambda: EdtCliInfo(found=True, path=edtcli, version="2026.2.2+21"),
    )
    assert result.status == "ok", result.diagnostics
    assert result.from_format == "edt"
    assert result.to_format == "xml"
    assert "edt-export" in result.steps

    fmt, path = _read_format(root)
    assert fmt == "xml"
    assert path == "."
    assert (root / "Configuration.xml").is_file()
    assert (root / ".1c-dev" / "project.yaml").is_file()
    assert not (root / PROJECT_FILE_NAME).exists()
    assert not (root / "src" / "Configuration" / "Configuration.mdo").exists()


def test_convert_roundtrip_mock(tmp_path: Path) -> None:
    root = _copy_edt_fixture(tmp_path)
    edtcli = tmp_path / "1cedtcli"
    edtcli.write_text("", encoding="utf-8")

    def discover() -> EdtCliInfo:
        return EdtCliInfo(found=True, path=edtcli, version="2026.2.2+21")

    to_xml = run_convert(root, to="xml", edt_run=_fake_edt_run, edt_discover=discover)
    assert to_xml.status == "ok"
    assert _read_format(root)[0] == "xml"

    to_edt = run_convert(root, to="edt", edt_run=_fake_edt_run, edt_discover=discover)
    assert to_edt.status == "ok"
    assert _read_format(root) == ("edt", ".")
    assert (root / PROJECT_FILE_NAME).is_file()
    assert (root / CONFIGURATION_MDO_REL).is_file()


def test_convert_same_format_fails(tmp_path: Path) -> None:
    root = _copy_edt_fixture(tmp_path)
    result = run_convert(root, to="edt")
    assert result.status == "failed"
    assert any(d.get("code") == CODE_CONVERT_DIRTY for d in result.diagnostics)


def test_convert_same_format_force_noop(tmp_path: Path) -> None:
    root = _copy_edt_fixture(tmp_path)
    result = run_convert(root, to="edt", force=True)
    assert result.status == "ok"
    assert result.steps == ["noop"]


def test_convert_missing_edtcli(tmp_path: Path) -> None:
    root = _write_xml_project(tmp_path)
    result = run_convert(
        root,
        to="edt",
        edt_discover=lambda: EdtCliInfo(found=False),
    )
    assert result.status == "failed"
    assert any(d.get("code") == CODE_EDTCLI_MISSING for d in result.diagnostics)


def test_convert_rollback_on_copy_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failed copy after backup must restore source and leave format unchanged."""
    from core.source import convert as convert_mod

    root = _write_xml_project(tmp_path)
    source = root / "src" / "cf"
    marker = (source / "Configuration.xml").read_text(encoding="utf-8")
    edtcli = tmp_path / "1cedtcli"
    edtcli.write_text("", encoding="utf-8")

    real_copy = convert_mod._copy_tree_into
    calls = {"n": 0}

    def boom_then_real(src: Path, dest: Path) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("simulated copy failure")
        real_copy(src, dest)

    monkeypatch.setattr("core.source.convert._copy_tree_into", boom_then_real)

    result = run_convert(
        root,
        to="edt",
        edt_run=_fake_edt_run,
        edt_discover=lambda: EdtCliInfo(found=True, path=edtcli, version="2026.2.2+21"),
    )
    assert result.status == "failed"
    assert any(d.get("code") == CODE_CONVERT_DIRTY for d in result.diagnostics)
    assert (source / "Configuration.xml").is_file()
    assert (source / "Configuration.xml").read_text(encoding="utf-8") == marker
    assert _read_format(root) == ("xml", "src/cf")
    assert not (source / PROJECT_FILE_NAME).exists()


def test_convert_rollback_on_manifest_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failed atomic manifest write must restore source and leave format unchanged."""
    root = _write_xml_project(tmp_path)
    source = root / "src" / "cf"
    marker = (source / "Configuration.xml").read_text(encoding="utf-8")
    edtcli = tmp_path / "1cedtcli"
    edtcli.write_text("", encoding="utf-8")

    def boom_manifest(_path: Path, _data: object) -> None:
        raise OSError("simulated manifest failure")

    monkeypatch.setattr("core.source.convert._write_manifest_atomic", boom_manifest)

    result = run_convert(
        root,
        to="edt",
        edt_run=_fake_edt_run,
        edt_discover=lambda: EdtCliInfo(found=True, path=edtcli, version="2026.2.2+21"),
    )
    assert result.status == "failed"
    assert any(d.get("code") == CODE_CONVERT_DIRTY for d in result.diagnostics)
    assert (source / "Configuration.xml").is_file()
    assert (source / "Configuration.xml").read_text(encoding="utf-8") == marker
    assert _read_format(root) == ("xml", "src/cf")
    assert not (source / PROJECT_FILE_NAME).exists()


def test_cli_source_convert_mock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _write_xml_project(tmp_path)
    monkeypatch.chdir(root)
    edtcli = tmp_path / "1cedtcli"
    edtcli.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        "core.source.convert.require_edtcli",
        lambda info=None: EdtCliInfo(found=True, path=edtcli, version="2026.2.2+21"),
    )

    def _import_stub(
        _edtcli: Path,
        *,
        configuration_files: Path,
        project: Path,
        platform_version: str = "8.5.1",
        **_kwargs: object,
    ) -> EdtCliRunResult:
        del configuration_files, platform_version
        return _fake_import(
            [
                str(edtcli),
                "-command",
                "import",
                "--project",
                str(project),
            ]
        )

    monkeypatch.setattr("core.source.convert.import_configuration", _import_stub)

    result = runner.invoke(app, ["source", "convert", "--to", "edt", "--output", "json"])
    assert result.exit_code == SUCCESS, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["toFormat"] == "edt"
    assert _read_format(root)[0] == "edt"


def test_cli_convert_already_edt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _copy_edt_fixture(tmp_path)
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["source", "convert", "--to", "edt", "--output", "json"])
    assert result.exit_code == PROJECT_ERROR
    payload = json.loads(result.output)
    assert payload["status"] == "failed"
    assert any(d["code"] == CODE_CONVERT_DIRTY for d in payload["diagnostics"])


def test_cli_convert_env_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapters.edtcli import EdtCliError

    root = _write_xml_project(tmp_path)
    monkeypatch.chdir(root)

    def _raise(*, info: EdtCliInfo | None = None) -> EdtCliInfo:
        del info
        raise EdtCliError(
            "1cedtcli не найден",
            code=CODE_EDTCLI_MISSING,
            diagnostics=[
                {
                    "severity": "error",
                    "code": CODE_EDTCLI_MISSING,
                    "message": "1cedtcli не найден",
                    "source": "edt",
                }
            ],
        )

    monkeypatch.setattr("core.source.convert.require_edtcli", _raise)
    result = runner.invoke(app, ["source", "convert", "--to", "edt", "--output", "json"])
    assert result.exit_code == ENV_UNAVAILABLE


def test_convert_extension_xml_to_edt_leaves_config(tmp_path: Path) -> None:
    """#162: --extension converts only nested source; config stays xml."""
    root = _write_xml_project_with_extension(tmp_path)
    config_marker = (root / "src" / "cf" / "Configuration.xml").read_text(encoding="utf-8")

    result = run_convert(
        root,
        to="edt",
        extension_id="tests",
        edt_run=_fake_edt_run,
        edt_discover=_edtcli_discover(tmp_path),
    )
    assert result.status == "ok", result.diagnostics
    assert result.extension_id == "tests"
    assert result.from_format == "xml"
    assert result.to_format == "edt"
    assert result.source_rel == "src/cfe/tests"
    assert "edt-import" in result.steps

    assert _read_format(root) == ("xml", "src/cf")
    assert _read_extension_format(root) == ("edt", "src/cfe/tests")
    assert (root / "src" / "cf" / "Configuration.xml").read_text(encoding="utf-8") == config_marker
    ext = root / "src" / "cfe" / "tests"
    assert (ext / PROJECT_FILE_NAME).is_file()
    assert (ext / CONFIGURATION_MDO_REL).is_file()
    assert not (ext / "Configuration.xml").exists()


def test_convert_extension_by_name_roundtrip(tmp_path: Path) -> None:
    """#162: resolve by name; edt→xml restores Designer XML; config untouched."""
    root = _write_xml_project_with_extension(tmp_path)
    discover = _edtcli_discover(tmp_path)

    to_edt = run_convert(
        root,
        to="edt",
        extension_id="Tests",
        edt_run=_fake_edt_run,
        edt_discover=discover,
    )
    assert to_edt.status == "ok", to_edt.diagnostics
    assert to_edt.extension_id == "tests"
    assert _read_extension_format(root) == ("edt", "src/cfe/tests")
    assert _read_format(root)[0] == "xml"

    to_xml = run_convert(
        root,
        to="xml",
        extension_id="tests",
        edt_run=_fake_edt_run,
        edt_discover=discover,
    )
    assert to_xml.status == "ok", to_xml.diagnostics
    assert _read_extension_format(root) == ("xml", "src/cfe/tests")
    assert _read_format(root) == ("xml", "src/cf")
    ext = root / "src" / "cfe" / "tests"
    assert (ext / "Configuration.xml").is_file()
    assert not (ext / PROJECT_FILE_NAME).exists()


def test_convert_config_leaves_extension(tmp_path: Path) -> None:
    """#162: without --extension only config converts; extension stays xml."""
    root = _write_xml_project_with_extension(tmp_path)
    ext_marker = (root / "src" / "cfe" / "tests" / "Configuration.xml").read_text(
        encoding="utf-8"
    )

    result = run_convert(
        root,
        to="edt",
        edt_run=_fake_edt_run,
        edt_discover=_edtcli_discover(tmp_path),
    )
    assert result.status == "ok", result.diagnostics
    assert result.extension_id is None
    assert _read_format(root) == ("edt", "src/cf")
    assert _read_extension_format(root) == ("xml", "src/cfe/tests")
    assert (
        root / "src" / "cfe" / "tests" / "Configuration.xml"
    ).read_text(encoding="utf-8") == ext_marker


def test_convert_extension_unknown(tmp_path: Path) -> None:
    root = _write_xml_project_with_extension(tmp_path)
    result = run_convert(root, to="edt", extension_id="missing")
    assert result.status == "failed"
    assert any("не найдено" in str(d.get("message", "")) for d in result.diagnostics)


def test_cli_source_convert_extension_mock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _write_xml_project_with_extension(tmp_path)
    monkeypatch.chdir(root)
    edtcli = tmp_path / "1cedtcli"
    edtcli.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        "core.source.convert.require_edtcli",
        lambda info=None: EdtCliInfo(found=True, path=edtcli, version="2026.2.2+21"),
    )

    def _import_stub(
        _edtcli: Path,
        *,
        configuration_files: Path,
        project: Path,
        platform_version: str = "8.5.1",
        **_kwargs: object,
    ) -> EdtCliRunResult:
        del configuration_files, platform_version
        return _fake_import(
            [
                str(edtcli),
                "-command",
                "import",
                "--project",
                str(project),
            ]
        )

    monkeypatch.setattr("core.source.convert.import_configuration", _import_stub)

    result = runner.invoke(
        app,
        ["source", "convert", "--to", "edt", "--extension", "tests", "--output", "json"],
    )
    assert result.exit_code == SUCCESS, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["extensionId"] == "tests"
    assert payload["toFormat"] == "edt"
    assert payload["sourcePath"] == "src/cfe/tests"
    assert _read_extension_format(root) == ("edt", "src/cfe/tests")
    assert _read_format(root)[0] == "xml"


@pytest.mark.integration
def test_convert_roundtrip_integration(tmp_path: Path) -> None:
    """Live 1cedtcli: edt_spike → xml → edt; format in manifest matches."""
    info = discover_edtcli()
    if not info.found or info.path is None:
        pytest.skip(EDTCLI_SKIP_MESSAGE)

    root = _copy_edt_fixture(tmp_path)

    to_xml = run_convert(root, to="xml")
    assert to_xml.status == "ok", to_xml.diagnostics
    assert _read_format(root)[0] == "xml"
    assert (root / "Configuration.xml").is_file()
    assert (root / "Catalogs" / "Products.xml").is_file()

    to_edt = run_convert(root, to="edt")
    assert to_edt.status == "ok", to_edt.diagnostics
    assert _read_format(root) == ("edt", ".")
    assert (root / PROJECT_FILE_NAME).is_file()
    assert (root / CONFIGURATION_MDO_REL).is_file()
    assert (root / "src" / "Catalogs" / "Products" / "Products.mdo").is_file()
    assert not (root / "Configuration.xml").exists()


def _write_project_with_edt_extension(tmp_path: Path) -> Path:
    """XML main config + nested extension seeded from edt_spike (live 1cedtcli)."""
    root = _write_xml_project(tmp_path)
    ext = root / "src" / "cfe" / "tests"
    shutil.copytree(FIXTURE, ext)
    manifest = root / ".1c-dev" / "project.yaml"
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    data["configurations"][0]["extensions"] = [
        {
            "id": "tests",
            "name": "Tests",
            "purpose": "tests",
            "source": {"format": "edt", "path": "src/cfe/tests"},
        }
    ]
    manifest.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return root


@pytest.mark.integration
def test_convert_extension_roundtrip_integration(tmp_path: Path) -> None:
    """Live 1cedtcli: nested extension edt → xml → edt; config untouched (#162)."""
    info = discover_edtcli()
    if not info.found or info.path is None:
        pytest.skip(EDTCLI_SKIP_MESSAGE)

    root = _write_project_with_edt_extension(tmp_path)
    config_before = _read_format(root)
    config_marker = (root / "src" / "cf" / "Configuration.xml").read_text(encoding="utf-8")
    ext = root / "src" / "cfe" / "tests"

    to_xml = run_convert(root, to="xml", extension_id="tests")
    assert to_xml.status == "ok", to_xml.diagnostics
    assert _read_extension_format(root) == ("xml", "src/cfe/tests")
    assert _read_format(root) == config_before
    assert (root / "src" / "cf" / "Configuration.xml").read_text(encoding="utf-8") == config_marker
    assert (ext / "Configuration.xml").is_file()
    assert not (ext / PROJECT_FILE_NAME).exists()

    to_edt = run_convert(root, to="edt", extension_id="tests")
    assert to_edt.status == "ok", to_edt.diagnostics
    assert _read_extension_format(root) == ("edt", "src/cfe/tests")
    assert _read_format(root) == config_before
    assert (root / "src" / "cf" / "Configuration.xml").read_text(encoding="utf-8") == config_marker
    assert (ext / PROJECT_FILE_NAME).is_file()
    assert (ext / CONFIGURATION_MDO_REL).is_file()
    assert not (ext / "Configuration.xml").exists()
