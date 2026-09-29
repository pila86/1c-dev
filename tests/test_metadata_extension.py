"""Tests for metadata.* on nested extensions (#112)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from adapters.source.mdclasses.resolve import resolve_jar, resolve_java
from cli.main import app
from core.exit_codes import SUCCESS
from core.extension import add_extension
from core.metadata import (
    catalog_from_parts,
    create_metadata,
    find_metadata,
    get_metadata,
    list_metadata,
)
from tests.helpers_project import bootstrap_configuration_project

runner = CliRunner()


def _project_with_extension(tmp_path: Path) -> Path:
    target = tmp_path / "shop"
    target.mkdir()
    init = bootstrap_configuration_project(target, name="Shop")
    assert init.status == "ok"
    added = add_extension(
        target,
        ext_id="custom",
        name="CustomExt",
        purpose="product",
    )
    assert added.status == "ok", added.diagnostics
    return target


def test_list_metadata_extension_by_id(tmp_path: Path) -> None:
    target = _project_with_extension(tmp_path)
    seen: list[Path] = []

    def fake_read(command: str, source_dir: Path, args: tuple[str, ...]) -> dict[str, Any]:
        assert command == "list"
        seen.append(source_dir)
        return {
            "status": "ok",
            "objects": [
                {
                    "type": "Language",
                    "name": "Русский",
                    "qname": "Language.Русский",
                },
                {
                    "type": "Role",
                    "name": "Custom_MainRole",
                    "qname": "Role.Custom_MainRole",
                },
            ],
        }

    result = list_metadata(target, extension_id="custom", read_fn=fake_read)
    assert result.status == "ok", result.diagnostics
    assert seen == [(target / "src" / "cfe" / "custom").resolve()]
    assert result.source_path == (target / "src" / "cfe" / "custom").resolve()
    assert {o["qname"] for o in result.objects} >= {
        "Language.Русский",
        "Role.Custom_MainRole",
    }


def test_list_metadata_extension_by_name(tmp_path: Path) -> None:
    target = _project_with_extension(tmp_path)

    def fake_read(command: str, source_dir: Path, args: tuple[str, ...]) -> dict[str, Any]:
        assert source_dir == (target / "src" / "cfe" / "custom").resolve()
        return {"status": "ok", "objects": []}

    result = list_metadata(target, extension_id="CustomExt", read_fn=fake_read)
    assert result.status == "ok"


def test_list_metadata_without_extension_stays_on_cf(tmp_path: Path) -> None:
    target = _project_with_extension(tmp_path)

    def fake_read(command: str, source_dir: Path, args: tuple[str, ...]) -> dict[str, Any]:
        assert source_dir == (target / "src" / "cf").resolve()
        return {"status": "ok", "objects": []}

    result = list_metadata(target, read_fn=fake_read)
    assert result.status == "ok"


def test_list_metadata_unknown_extension(tmp_path: Path) -> None:
    target = _project_with_extension(tmp_path)
    result = list_metadata(target, extension_id="missing")
    assert result.status == "error"
    assert any(d.get("code") == "1CM001" for d in result.diagnostics)


def test_create_metadata_on_extension_mock(tmp_path: Path) -> None:
    target = _project_with_extension(tmp_path)
    ext_src = (target / "src" / "cfe" / "custom").resolve()

    def fake_compile(source_dir: Path, dsl: dict[str, Any]) -> list[str]:
        assert source_dir == ext_src
        assert dsl["name"] == "Custom_Products"
        catalogs = source_dir / "Catalogs"
        catalogs.mkdir(parents=True)
        (catalogs / "Custom_Products.xml").write_text("<Catalog/>", encoding="utf-8")
        return ["Catalogs/Custom_Products.xml"]

    catalog = catalog_from_parts(
        qualified_name="Catalog.Custom_Products",
        synonym="Товары расширения",
    )
    result = create_metadata(
        target,
        catalog,
        extension_id="custom",
        compile_fn=fake_compile,
    )
    assert result.status == "ok", result.diagnostics
    assert result.source_path == ext_src


def test_cli_metadata_list_extension(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _project_with_extension(tmp_path)
    monkeypatch.chdir(target)

    def fake_run(command: str, source_dir: Path, *args: str) -> dict[str, Any]:
        assert command == "list"
        assert source_dir == (target / "src" / "cfe" / "custom").resolve()
        return {
            "status": "ok",
            "objects": [
                {
                    "type": "Language",
                    "name": "Русский",
                    "qname": "Language.Русский",
                }
            ],
        }

    monkeypatch.setattr("core.metadata.read.run_md_reader", fake_run)

    result = runner.invoke(
        app,
        ["metadata", "list", "--extension", "custom", "--output", "json"],
    )
    assert result.exit_code == SUCCESS, result.output
    assert "Language.Русский" in result.output


@pytest.mark.integration
def test_metadata_extension_with_real_md_reader(tmp_path: Path) -> None:
    java = resolve_java()
    jar = resolve_jar()
    if not java.found or not jar.found:
        pytest.skip(
            "md-reader jar / Java 21+ недоступны (запустите scripts/fetch-md-reader.sh)"
        )

    target = _project_with_extension(tmp_path)
    listed = list_metadata(target, extension_id="custom")
    assert listed.status == "ok", listed.diagnostics
    assert listed.source_path == (target / "src" / "cfe" / "custom").resolve()
    qnames = {o["qname"] for o in listed.objects}
    assert any(q.startswith("Language.") for q in qnames)

    from adapters.source.xmlgen.resolve import resolve_jar as resolve_xmlgen
    from adapters.source.xmlgen.resolve import resolve_java as resolve_java_xml

    xmlgen = resolve_xmlgen()
    if not (xmlgen.found and resolve_java_xml().found):
        return

    created = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="Catalog.Custom_Products",
            synonym="Товары расширения",
            attr_specs=["Article:String:50:Артикул"],
        ),
        extension_id="custom",
    )
    assert created.status == "ok", created.diagnostics
    got = get_metadata(target, "Catalog.Custom_Products", extension_id="custom")
    assert got.status == "ok", got.diagnostics
    assert got.ir is not None
    assert got.ir["name"] == "Custom_Products"
    found = find_metadata(target, "Товар", extension_id="custom")
    assert found.status == "ok"
    assert any(o.get("qname") == "Catalog.Custom_Products" for o in found.objects)

    # Regression: main configuration still lists without --extension
    main_list = list_metadata(target)
    assert main_list.status == "ok", main_list.diagnostics
    assert main_list.source_path == (target / "src" / "cf").resolve()
