"""Tests for metadata IR and create (ADR-007 / #23)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from adapters.source.xmlgen.compile import ir_to_xmlgen_dsl
from adapters.source.xmlgen.resolve import resolve_jar, resolve_java
from cli.main import app
from core.exit_codes import PROJECT_ERROR, SUCCESS
from core.metadata import (
    IrError,
    catalog_from_json,
    catalog_from_parts,
    create_metadata,
    parse_attr_spec,
    parse_qualified_name,
    parse_ts_attr_spec,
    parse_ts_spec,
)
from core.project import init_project

runner = CliRunner()


def test_parse_qualified_name() -> None:
    assert parse_qualified_name("Catalog.Products") == ("Catalog", "Products")
    assert parse_qualified_name("Document.Sales") == ("Document", "Sales")
    with pytest.raises(IrError) as exc:
        parse_qualified_name("Report.Sales")
    assert exc.value.code == "1CM002"


def test_parse_attr_spec() -> None:
    a = parse_attr_spec("Article:String:50:Артикул")
    assert a.name == "Article"
    assert a.type == "String"
    assert a.length == 50
    assert a.synonym == "Артикул"
    n = parse_attr_spec("Price:Number:15.2:Цена")
    assert n.type == "Number"
    assert n.precision == 15
    assert n.scale == 2
    ref = parse_attr_spec("Counterparty:Ref:Catalog.Products:Контрагент")
    assert ref.type == "Ref"
    assert ref.reference == "Catalog.Products"


def test_parse_ts_specs() -> None:
    ts = parse_ts_spec("Products:Товары")
    assert ts.name == "Products"
    assert ts.synonym == "Товары"
    ts_name, attr = parse_ts_attr_spec("Products.Qty:Number:15.3:Количество")
    assert ts_name == "Products"
    assert attr.name == "Qty"
    assert attr.precision == 15
    assert attr.scale == 3


def test_catalog_from_json_prd_shape() -> None:
    cat = catalog_from_json(
        {
            "type": "Catalog",
            "name": "Products",
            "synonym": "Товары",
            "attributes": [
                {
                    "name": "Article",
                    "synonym": "Артикул",
                    "type": "String",
                    "length": 50,
                }
            ],
        }
    )
    assert cat.qualified_name == "Catalog.Products"
    assert cat.attributes[0].length == 50
    dsl = ir_to_xmlgen_dsl(cat.to_dict())
    assert dsl["attributes"][0]["type"] == "String(50)"


def test_document_from_json_with_tabular_sections() -> None:
    doc = catalog_from_json(
        {
            "type": "Document",
            "name": "Sales",
            "synonym": "Продажи",
            "attributes": [
                {"name": "Comment", "type": "String", "length": 100},
                {
                    "name": "Counterparty",
                    "type": "Ref",
                    "reference": "Catalog.Products",
                },
            ],
            "tabularSections": [
                {
                    "name": "Products",
                    "synonym": "Товары",
                    "attributes": [
                        {
                            "name": "Qty",
                            "type": "Number",
                            "precision": 15,
                            "scale": 3,
                        }
                    ],
                }
            ],
        }
    )
    assert doc.qualified_name == "Document.Sales"
    assert len(doc.tabular_sections) == 1
    assert doc.tabular_sections[0].synonym == "Товары"
    dsl = ir_to_xmlgen_dsl(doc.to_dict())
    assert dsl["type"] == "Document"
    assert dsl["tabularSections"]["Products"][0]["type"] == "Number(15,3)"
    assert dsl["attributes"][1]["type"] == "CatalogRef.Products"


def test_document_from_parts_cli() -> None:
    doc = catalog_from_parts(
        qualified_name="Document.Sales",
        synonym="Продажи",
        attr_specs=["Comment:String:100:Комментарий"],
        ts_specs=["Products:Товары"],
        ts_attr_specs=["Products.Qty:Number:15.3:Количество"],
    )
    assert doc.type == "Document"
    assert doc.tabular_sections[0].name == "Products"
    assert doc.tabular_sections[0].attributes[0].name == "Qty"


def test_create_metadata_mock(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    init = init_project(target, project_type="configuration", name="Shop")
    assert init.status == "ok"

    def fake_compile(source_dir: Path, dsl: dict[str, Any]) -> list[str]:
        assert dsl["name"] == "Products"
        catalogs = source_dir / "Catalogs"
        catalogs.mkdir(parents=True)
        (catalogs / "Products.xml").write_text("<Catalog/>", encoding="utf-8")
        cfg = source_dir / "Configuration.xml"
        text = cfg.read_text(encoding="utf-8-sig")
        text = text.replace(
            "<Language>Русский</Language>",
            "<Language>Русский</Language>\r\n\t\t\t<Catalog>Products</Catalog>",
        )
        cfg.write_text(text, encoding="utf-8-sig", newline="")
        return ["Catalogs/Products.xml", "Configuration.xml"]

    catalog = catalog_from_parts(
        qualified_name="Catalog.Products",
        synonym="Товары",
        attr_specs=["Article:String:50:Артикул"],
    )
    result = create_metadata(target, catalog, compile_fn=fake_compile)
    assert result.status == "ok"
    assert result.object == "Catalog.Products"
    assert any("Catalogs/Products.xml" in p for p in result.created)
    assert (target / "src" / "cf" / "Catalogs" / "Products.xml").is_file()


def test_create_document_mock(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(target, project_type="configuration", name="Shop").status == "ok"

    followups: list[tuple[str, str]] = []

    def fake_compile(source_dir: Path, dsl: dict[str, Any]) -> list[str]:
        assert dsl["type"] == "Document"
        assert dsl["name"] == "Sales"
        assert "Products" in dsl["tabularSections"]
        documents = source_dir / "Documents"
        documents.mkdir(parents=True)
        (documents / "Sales.xml").write_text("<Document/>", encoding="utf-8")
        cfg = source_dir / "Configuration.xml"
        text = cfg.read_text(encoding="utf-8-sig")
        text = text.replace(
            "<Language>Русский</Language>",
            "<Language>Русский</Language>\r\n\t\t\t<Document>Sales</Document>",
        )
        cfg.write_text(text, encoding="utf-8-sig", newline="")
        return ["Documents/Sales.xml", "Configuration.xml"]

    def fake_followup(object_xml: Path, ops: list[Any]) -> None:
        assert object_xml.name == "Sales.xml"
        for op in ops:
            followups.append((op.op, op.value))

    doc = catalog_from_parts(
        qualified_name="Document.Sales",
        synonym="Продажи",
        attr_specs=["Comment:String:100"],
        ts_specs=["Products:Товары"],
        ts_attr_specs=["Products.Qty:Number:15.3"],
    )
    result = create_metadata(
        target,
        doc,
        compile_fn=fake_compile,
        followup_fn=fake_followup,
    )
    assert result.status == "ok"
    assert result.object == "Document.Sales"
    assert any("Documents/Sales.xml" in p for p in result.created)
    assert followups == [("modify-ts", "Products: synonym=Товары")]


def test_create_duplicate(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")
    catalogs = target / "src" / "cf" / "Catalogs"
    catalogs.mkdir()
    (catalogs / "Products.xml").write_text("x", encoding="utf-8")
    catalog = catalog_from_parts(qualified_name="Catalog.Products")
    result = create_metadata(
        target,
        catalog,
        compile_fn=lambda *_a, **_k: [],
    )
    assert result.status == "error"
    assert any(d.get("code") == "1CM003" for d in result.diagnostics)


def test_create_missing_xmlgen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")
    monkeypatch.delenv("ONEC_XMLGEN_JAR", raising=False)
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("JAVA_HOME", raising=False)
    # point cache to empty dir
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "empty-cache"))
    catalog = catalog_from_parts(qualified_name="Catalog.Products")
    result = create_metadata(target, catalog)
    assert result.status == "error"
    assert any(d.get("code") == "1CM006" for d in result.diagnostics)


def test_cli_create_mock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")

    def fake_compile(source_dir: Path, dsl: dict[str, Any]) -> list[str]:
        catalogs = source_dir / "Catalogs"
        catalogs.mkdir(parents=True)
        (catalogs / "Products.xml").write_text("<Catalog/>", encoding="utf-8")
        return ["Catalogs/Products.xml"]

    monkeypatch.setattr(
        "core.metadata.create.compile_metadata",
        fake_compile,
    )
    from adapters.source.xmlgen.resolve import ToolResolve

    monkeypatch.setattr(
        "core.metadata.create.resolve_java",
        lambda: ToolResolve(found=True, path=Path("/usr/bin/java"), version="21"),
    )
    monkeypatch.setattr(
        "core.metadata.create.resolve_jar",
        lambda: ToolResolve(found=True, path=tmp_path / "xml-gen.jar"),
    )
    monkeypatch.chdir(target)

    result = runner.invoke(
        app,
        [
            "metadata",
            "create",
            "Catalog.Products",
            "--synonym",
            "Товары",
            "--attr",
            "Article:String:50:Артикул",
            "--output",
            "json",
        ],
    )
    assert result.exit_code == SUCCESS, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["object"] == "Catalog.Products"


def test_cli_create_document_mock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")

    def fake_compile(source_dir: Path, dsl: dict[str, Any]) -> list[str]:
        assert dsl["type"] == "Document"
        documents = source_dir / "Documents"
        documents.mkdir(parents=True)
        (documents / "Sales.xml").write_text("<Document/>", encoding="utf-8")
        return ["Documents/Sales.xml"]

    monkeypatch.setattr("core.metadata.create.compile_metadata", fake_compile)
    monkeypatch.setattr(
        "core.metadata.create._apply_tabular_synonyms",
        lambda *_a, **_k: None,
    )
    from adapters.source.xmlgen.resolve import ToolResolve

    monkeypatch.setattr(
        "core.metadata.create.resolve_java",
        lambda: ToolResolve(found=True, path=Path("/usr/bin/java"), version="21"),
    )
    monkeypatch.setattr(
        "core.metadata.create.resolve_jar",
        lambda: ToolResolve(found=True, path=tmp_path / "xml-gen.jar"),
    )
    monkeypatch.chdir(target)

    result = runner.invoke(
        app,
        [
            "metadata",
            "create",
            "Document.Sales",
            "--synonym",
            "Продажи",
            "--attr",
            "Comment:String:100:Комментарий",
            "--ts",
            "Products:Товары",
            "--ts-attr",
            "Products.Qty:Number:15.3:Количество",
            "--output",
            "json",
        ],
    )
    assert result.exit_code == SUCCESS, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["object"] == "Document.Sales"


def test_cli_bad_type(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")
    monkeypatch.chdir(target)
    result = runner.invoke(
        app,
        ["metadata", "create", "Enum.Statuses", "--output", "json"],
    )
    assert result.exit_code == PROJECT_ERROR
    payload = json.loads(result.output)
    assert payload["diagnostics"][0]["code"] == "1CM002"


@pytest.mark.integration
def test_create_with_real_xmlgen(tmp_path: Path) -> None:
    jar = resolve_jar()
    java = resolve_java()
    if not jar.found or not java.found:
        pytest.skip("xml-gen jar / Java 17+ недоступны (запустите scripts/fetch-xml-gen.sh)")

    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")
    catalog = catalog_from_parts(
        qualified_name="Catalog.Products",
        synonym="Товары",
        attr_specs=["Article:String:50:Артикул"],
    )
    result = create_metadata(target, catalog)
    assert result.status == "ok", result.diagnostics
    products = target / "src" / "cf" / "Catalogs" / "Products.xml"
    assert products.is_file()
    text = products.read_text(encoding="utf-8-sig")
    assert "Article" in text
    cfg = (target / "src" / "cf" / "Configuration.xml").read_text(encoding="utf-8-sig")
    assert "<Catalog>Products</Catalog>" in cfg
    from core.project import validate_project

    assert validate_project(target).status == "ok"


@pytest.mark.integration
def test_create_document_with_real_xmlgen(tmp_path: Path) -> None:
    jar = resolve_jar()
    java = resolve_java()
    if not jar.found or not java.found:
        pytest.skip("xml-gen jar / Java 17+ недоступны (запустите scripts/fetch-xml-gen.sh)")

    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")

    # Ref target catalog first
    cat = create_metadata(
        target,
        catalog_from_parts(qualified_name="Catalog.Products", synonym="Товары"),
    )
    assert cat.status == "ok", cat.diagnostics

    doc = catalog_from_parts(
        qualified_name="Document.Sales",
        synonym="Продажи",
        attr_specs=[
            "Comment:String:100:Комментарий",
            "Counterparty:Ref:Catalog.Products:Контрагент",
        ],
        ts_specs=["Lines:Товары"],
        ts_attr_specs=[
            "Lines.Item:Ref:Catalog.Products:Товар",
            "Lines.Qty:Number:15.3:Количество",
        ],
    )
    result = create_metadata(target, doc)
    assert result.status == "ok", result.diagnostics
    sales = target / "src" / "cf" / "Documents" / "Sales.xml"
    assert sales.is_file()
    text = sales.read_text(encoding="utf-8-sig")
    assert "Comment" in text
    assert "Counterparty" in text
    assert "Lines" in text
    assert "Qty" in text
    assert "Товары" in text  # TS synonym via modify-ts
    cfg = (target / "src" / "cf" / "Configuration.xml").read_text(encoding="utf-8-sig")
    assert "<Document>Sales</Document>" in cfg
