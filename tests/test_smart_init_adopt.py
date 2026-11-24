"""Smart init adopt + external test paths (ADR-034)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from cli.main import app
from core.extension import add_extension
from core.project import init_project, validate_project
from core.project.discover_sources import discover_sources
from core.test.discover import discover_modules
from core.test.suites import parse_suites

runner = CliRunner()
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(autouse=True)
def _isolate_external_tools_share(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "_xdg_data"))


def _copy_fixture(name: str, dest: Path) -> Path:
    src = FIXTURES / name
    shutil.copytree(src, dest)
    return dest


def test_discover_sources_xml_nested(tmp_path: Path) -> None:
    root = _copy_fixture("adopt_xml_nested", tmp_path / "proj")
    result = discover_sources(root)
    assert len(result.configurations) == 1
    conf = result.configurations[0]
    assert conf.format == "xml"
    assert conf.rel_path == "src/cf"
    assert conf.name == "AdoptXmlNested"
    assert result.extensions == []


def test_discover_sources_edt_nested(tmp_path: Path) -> None:
    root = _copy_fixture("adopt_edt_nested", tmp_path / "proj")
    result = discover_sources(root)
    assert len(result.configurations) == 1
    conf = result.configurations[0]
    assert conf.format == "edt"
    assert conf.rel_path == "wrap/edt"
    assert conf.name == "AdoptEdtNested"


def test_discover_sources_with_tests(tmp_path: Path) -> None:
    root = _copy_fixture("adopt_with_tests", tmp_path / "proj")
    result = discover_sources(root)
    assert len(result.configurations) == 1
    assert result.configurations[0].rel_path == "src/main"
    assert len(result.extensions) == 1
    ext = result.extensions[0]
    assert ext.purpose == "tests"
    assert ext.rel_path == "src/cfe/tests_ext"


def test_discover_orphan_extensions_only(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    ext = root / "src" / "cfe" / "only_ext"
    ext.mkdir(parents=True)
    shutil.copy(
        FIXTURES / "adopt_with_tests" / "src" / "cfe" / "tests_ext" / "Configuration.xml",
        ext / "Configuration.xml",
    )
    result = discover_sources(root)
    assert result.configurations == []
    assert result.extensions == []
    assert any(d.get("code") == "1CP030" for d in result.diagnostics)


def test_init_empty_scope_unchanged(tmp_path: Path) -> None:
    target = tmp_path / "empty"
    target.mkdir()
    result = init_project(target, project_type="configuration", name="Empty")
    assert result.status == "ok"
    assert result.manifest is not None
    assert result.manifest["configurations"] == []
    assert result.adopted is None or result.adopted.get("configurations") == []


def test_init_adopts_xml_nested(tmp_path: Path) -> None:
    target = _copy_fixture("adopt_xml_nested", tmp_path / "shop")
    result = init_project(target, project_type="configuration", name="Shop")
    assert result.status == "ok"
    assert result.adopted is not None
    assert len(result.adopted["configurations"]) == 1
    assert result.manifest is not None
    conf = result.manifest["configurations"][0]
    assert conf["source"]["format"] == "xml"
    assert conf["source"]["path"] == "src/cf"
    assert conf["id"] == "AdoptXmlNested"
    assert result.manifest["runtimes"]
    assert not (target / "src" / "cf" / "Configuration.xml").read_text(
        encoding="utf-8-sig"
    ).startswith("{{")  # no template overwrite


def test_init_adopts_edt_nested(tmp_path: Path) -> None:
    target = _copy_fixture("adopt_edt_nested", tmp_path / "edtproj")
    result = init_project(target, project_type="configuration")
    assert result.status == "ok"
    assert result.manifest is not None
    conf = result.manifest["configurations"][0]
    assert conf["source"]["format"] == "edt"
    assert conf["source"]["path"] == "wrap/edt"


def test_init_adopts_tests_suite(tmp_path: Path) -> None:
    target = _copy_fixture("adopt_with_tests", tmp_path / "withtests")
    result = init_project(target, project_type="configuration")
    assert result.status == "ok"
    assert result.manifest is not None
    conf = result.manifest["configurations"][0]
    exts = conf["extensions"]
    assert len(exts) == 1
    assert exts[0]["purpose"] == "tests"
    assert conf["tests"][0]["runner"] == "yaxunit"
    assert exts[0]["id"] in conf["tests"][0]["extensions"]


def test_init_config_ignored_when_adopted(tmp_path: Path) -> None:
    target = _copy_fixture("adopt_xml_nested", tmp_path / "cfg")
    result = init_project(
        target,
        project_type="configuration",
        config="ShouldNotScaffold",
    )
    assert result.status == "ok"
    assert result.manifest is not None
    ids = [c["id"] for c in result.manifest["configurations"]]
    assert "ShouldNotScaffold" not in ids
    assert any(d.get("code") == "1CP032" for d in result.diagnostics)
    assert not (target / "src" / "ShouldNotScaffold").exists()


def test_extension_add_external_path(tmp_path: Path) -> None:
    scope = tmp_path / "scope"
    scope.mkdir()
    init = init_project(scope, project_type="configuration", config="main")
    assert init.status == "ok"

    external = tmp_path / "shared-tests" / "src" / "cfe" / "shared"
    shutil.copytree(
        FIXTURES / "adopt_with_tests" / "src" / "cfe" / "tests_ext",
        external,
    )

    result = add_extension(
        scope,
        ext_id="shared_tests",
        name="SharedTests",
        purpose="tests",
        source_path=external,
        format="xml",
    )
    assert result.status == "ok", result.diagnostics
    assert result.manifest is not None
    conf = result.manifest["configurations"][0]
    ext = conf["extensions"][0]
    assert ext["purpose"] == "tests"
    assert ext["source"]["path"].startswith("..")
    assert conf["tests"][0]["id"] == "unit"
    assert "shared_tests" in conf["tests"][0]["extensions"]

    suites, diags = parse_suites(conf)
    assert diags == []
    assert suites is not None
    modules = discover_modules(scope, suites)
    assert any(m["name"] == "ОМ_Тест" for m in modules)


def test_extension_add_path_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scope = tmp_path / "scope"
    scope.mkdir()
    assert init_project(scope, project_type="configuration", config="main").status == "ok"

    external = tmp_path / "ext_src"
    shutil.copytree(
        FIXTURES / "adopt_with_tests" / "src" / "cfe" / "tests_ext",
        external,
    )

    monkeypatch.chdir(scope)
    result = runner.invoke(
        app,
        [
            "extension",
            "add",
            "--id",
            "cli_tests",
            "--purpose",
            "tests",
            "--path",
            str(external),
            "--format",
            "xml",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    validated = validate_project(scope)
    assert validated.status == "ok"
    assert validated.manifest is not None
    conf = validated.manifest["configurations"][0]
    assert any(e["id"] == "cli_tests" for e in conf["extensions"])


def test_validate_rejects_external_product_path(tmp_path: Path) -> None:
    scope = tmp_path / "scope"
    scope.mkdir()
    assert init_project(scope, project_type="configuration", config="main").status == "ok"
    manifest = scope / ".1c-dev" / "project.yaml"
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    conf = data["configurations"][0]
    conf["extensions"] = [
        {
            "id": "bad",
            "name": "Bad",
            "purpose": "product",
            "source": {"format": "xml", "path": "../outside"},
        }
    ]
    manifest.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    result = validate_project(scope)
    assert result.status == "error"
    assert any("purpose: tests" in d.get("message", "") for d in result.diagnostics)
