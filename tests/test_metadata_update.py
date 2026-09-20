"""Tests for metadata.update (ADR-011 / #22)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from adapters.source.xmlgen import EditOp, EditResult
from adapters.source.xmlgen.edit import _parse_edit_output
from adapters.source.xmlgen.resolve import resolve_jar, resolve_java
from cli.main import app
from core.exit_codes import PROJECT_ERROR, SUCCESS
from core.metadata import attr_to_xmlgen_shorthand, ops_from_attr, parse_attr_spec, update_metadata
from core.metadata.result import MetadataResult
from core.project import init_project

runner = CliRunner()


def _init_shop(tmp_path: Path) -> Path:
    target = tmp_path / "shop"
    target.mkdir()
    init = init_project(target, project_type="configuration", name="Shop")
    assert init.status == "ok"
    catalogs = target / "src" / "cf" / "Catalogs"
    catalogs.mkdir(parents=True)
    (catalogs / "Products.xml").write_text("<Catalog/>", encoding="utf-8")
    return target


def test_attr_to_xmlgen_shorthand() -> None:
    a = parse_attr_spec("Article:String:50:Артикул")
    assert attr_to_xmlgen_shorthand(a) == "Article:String(50)"
    ops = ops_from_attr(a)
    assert ops[0] == EditOp("add-attribute", "Article:String(50)")
    assert ops[1] == EditOp("modify-attribute", "Article: synonym=Артикул")

    ref = parse_attr_spec("Counterparty:Ref:Catalog.Counterparties:Контрагент")
    assert attr_to_xmlgen_shorthand(ref) == "Counterparty:CatalogRef.Counterparties"


def test_parse_edit_output_warn() -> None:
    stdout = """\
[INFO] Object: Catalog.Products
[WARN] Attribute 'Price' already exists, skipping

=== meta-edit summary ===
  Object:   Catalog.Products
  Added:    0
  Removed:  0
  Modified: 0
  Warnings: 1
  No changes applied.
"""
    result = _parse_edit_output(stdout, object_xml=Path("Catalogs/Products.xml"))
    assert result.added == 0
    assert result.warnings == ["Attribute 'Price' already exists, skipping"]
    assert result.changed_paths == []


def test_update_add_modify_remove_mock(tmp_path: Path) -> None:
    target = _init_shop(tmp_path)
    calls: list[EditOp] = []

    def fake_edit(object_xml: Path, operations: list[EditOp]) -> EditResult:
        assert object_xml.name == "Products.xml"
        calls.extend(operations)
        return EditResult(
            changed_paths=["Catalogs/Products.xml"],
            added=1 if operations[0].op == "add-attribute" else 0,
            modified=1 if operations[0].op == "modify-attribute" else 0,
            removed=1 if operations[0].op == "remove-attribute" else 0,
        )

    def fake_get(start: Path | None, qname: str, **_kw: Any) -> MetadataResult:
        return MetadataResult(
            status="ok",
            object=qname,
            ir={
                "type": "Catalog",
                "name": "Products",
                "qname": qname,
                "attributes": [{"name": "Price", "type": "Number"}],
            },
        )

    result = update_metadata(
        target,
        "Catalog.Products",
        [EditOp("add-attribute", "Price:Number(15,2)")],
        edit_fn=fake_edit,
        get_fn=fake_get,
    )
    assert result.status == "ok"
    assert result.updated
    assert result.ir is not None
    assert result.ir["attributes"][0]["name"] == "Price"

    result = update_metadata(
        target,
        "Catalog.Products",
        [EditOp("modify-attribute", "Price: synonym=Цена")],
        edit_fn=fake_edit,
        get_fn=fake_get,
    )
    assert result.status == "ok"

    result = update_metadata(
        target,
        "Catalog.Products",
        [EditOp("remove-attribute", "Price")],
        edit_fn=fake_edit,
        get_fn=fake_get,
    )
    assert result.status == "ok"
    assert [c.op for c in calls] == [
        "add-attribute",
        "modify-attribute",
        "remove-attribute",
    ]


def test_update_duplicate_warning(tmp_path: Path) -> None:
    target = _init_shop(tmp_path)

    def fake_edit(_object_xml: Path, _operations: list[EditOp]) -> EditResult:
        return EditResult(
            warnings=["Attribute 'Price' already exists, skipping"],
        )

    def fake_get(start: Path | None, qname: str, **_kw: Any) -> MetadataResult:
        return MetadataResult(status="ok", object=qname, ir={"type": "Catalog", "name": "Products"})

    result = update_metadata(
        target,
        "Catalog.Products",
        [EditOp("add-attribute", "Price:Number(15,2)")],
        edit_fn=fake_edit,
        get_fn=fake_get,
    )
    assert result.status == "ok"
    assert result.updated == []
    assert any(d.get("severity") == "warning" for d in result.diagnostics)
    assert "already exists" in result.diagnostics[0]["message"]


def test_update_empty_ops(tmp_path: Path) -> None:
    target = _init_shop(tmp_path)
    result = update_metadata(target, "Catalog.Products", [])
    assert result.status == "error"
    assert any(d.get("code") == "1CM002" for d in result.diagnostics)


def test_update_not_found(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")
    result = update_metadata(
        target,
        "Catalog.Missing",
        [EditOp("add-attribute", "X:String(10)")],
        edit_fn=lambda *_a, **_k: EditResult(),
    )
    assert result.status == "error"
    assert any(d.get("code") == "1CM008" for d in result.diagnostics)


def test_update_rejects_document(tmp_path: Path) -> None:
    target = _init_shop(tmp_path)
    result = update_metadata(
        target,
        "Document.Sales",
        [EditOp("add-attribute", "X:String(10)")],
        edit_fn=lambda *_a, **_k: EditResult(),
    )
    assert result.status == "error"
    assert any(d.get("code") == "1CM002" for d in result.diagnostics)


def test_cli_update_unequal_op_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = _init_shop(tmp_path)
    monkeypatch.chdir(target)
    result = runner.invoke(
        app,
        [
            "metadata",
            "update",
            "Catalog.Products",
            "--op",
            "add-attribute",
            "--output",
            "json",
        ],
    )
    assert result.exit_code == PROJECT_ERROR
    payload = json.loads(result.output)
    assert payload["diagnostics"][0]["code"] == "1CM002"


def test_cli_attr_sugar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = _init_shop(tmp_path)
    monkeypatch.chdir(target)
    seen: list[EditOp] = []

    def fake_update(
        start: Path | None,
        qname: str,
        operations: list[EditOp],
        **_kw: Any,
    ) -> MetadataResult:
        seen.extend(operations)
        return MetadataResult(status="ok", object=qname, updated=["src/cf/Catalogs/Products.xml"])

    monkeypatch.setattr("cli.metadata.update_metadata", fake_update)
    result = runner.invoke(
        app,
        [
            "metadata",
            "update",
            "Catalog.Products",
            "--attr",
            "Price:Number:15.2:Цена",
            "--output",
            "json",
        ],
    )
    assert result.exit_code == SUCCESS, result.output
    assert seen[0].op == "add-attribute"
    assert seen[0].value == "Price:Number(15,2)"
    assert seen[1].op == "modify-attribute"
    assert "synonym=Цена" in seen[1].value
    payload = json.loads(result.output)
    assert payload["status"] == "ok"


def test_cli_from_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = _init_shop(tmp_path)
    monkeypatch.chdir(target)
    ops_file = target / "ops.json"
    ops_file.write_text(
        json.dumps(
            {
                "operations": [
                    {"op": "add-attribute", "value": "Price:Number(15,2)"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    seen: list[EditOp] = []

    def fake_update(
        start: Path | None,
        qname: str,
        operations: list[EditOp],
        **_kw: Any,
    ) -> MetadataResult:
        seen.extend(operations)
        return MetadataResult(status="ok", object=qname)

    monkeypatch.setattr("cli.metadata.update_metadata", fake_update)
    result = runner.invoke(
        app,
        [
            "metadata",
            "update",
            "Catalog.Products",
            "--from-json",
            str(ops_file),
            "--output",
            "json",
        ],
    )
    assert result.exit_code == SUCCESS, result.output
    assert seen == [EditOp("add-attribute", "Price:Number(15,2)")]


@pytest.mark.integration
def test_update_with_real_xmlgen(tmp_path: Path) -> None:
    jar = resolve_jar()
    java = resolve_java()
    if not jar.found or not java.found:
        pytest.skip("xml-gen jar / Java 17+ недоступны (запустите scripts/fetch-xml-gen.sh)")

    from adapters.source.mdclasses.resolve import resolve_jar as resolve_md
    from adapters.source.mdclasses.resolve import resolve_java as resolve_md_java
    from core.metadata import catalog_from_parts, create_metadata, get_metadata

    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")
    created = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="Catalog.Products",
            synonym="Товары",
            attr_specs=["Article:String:50:Артикул"],
        ),
    )
    assert created.status == "ok", created.diagnostics

    products = target / "src" / "cf" / "Catalogs" / "Products.xml"
    assert products.is_file()

    added = update_metadata(
        target,
        "Catalog.Products",
        [EditOp("add-attribute", "Price:Number(15,2)")],
    )
    assert added.status == "ok", added.diagnostics
    assert added.updated
    text = products.read_text(encoding="utf-8-sig")
    assert "Price" in text

    modified = update_metadata(
        target,
        "Catalog.Products",
        [EditOp("modify-attribute", "Price: synonym=Цена")],
    )
    assert modified.status == "ok", modified.diagnostics
    text = products.read_text(encoding="utf-8-sig")
    assert "Цена" in text

    # Number(15,2) → Number(10,0): явная смена type= (не только synonym)
    retyped = update_metadata(
        target,
        "Catalog.Products",
        [EditOp("modify-attribute", "Price: type=Number(10,0)")],
    )
    assert retyped.status == "ok", retyped.diagnostics
    text = products.read_text(encoding="utf-8-sig")
    assert "<v8:Digits>10</v8:Digits>" in text
    assert "<v8:FractionDigits>0</v8:FractionDigits>" in text
    assert "<v8:Digits>15</v8:Digits>" not in text

    checksum = hashlib.sha256(products.read_bytes()).hexdigest()
    dup = update_metadata(
        target,
        "Catalog.Products",
        [EditOp("add-attribute", "Price:Number(10,0)")],
    )
    assert dup.status == "ok", dup.diagnostics
    assert any(d.get("severity") == "warning" for d in dup.diagnostics)
    assert hashlib.sha256(products.read_bytes()).hexdigest() == checksum

    md_java = resolve_md_java()
    md_jar = resolve_md()
    if md_java.found and md_jar.found:
        got = get_metadata(target, "Catalog.Products")
        assert got.status == "ok", got.diagnostics
        assert got.ir is not None
        attrs = {
            a.get("name"): a
            for a in (got.ir.get("attributes") or [])
            if isinstance(a, dict)
        }
        assert "Price" in attrs
        assert "Article" in attrs
        price = attrs["Price"]
        assert price.get("type") == "Number"
        assert price.get("precision") == 10
        assert price.get("scale") == 0

    removed = update_metadata(
        target,
        "Catalog.Products",
        [EditOp("remove-attribute", "Price")],
    )
    assert removed.status == "ok", removed.diagnostics
    text = products.read_text(encoding="utf-8-sig")
    assert "<Name>Price</Name>" not in text

    if md_java.found and md_jar.found:
        got2 = get_metadata(target, "Catalog.Products")
        assert got2.status == "ok", got2.diagnostics
        names2 = {
            a.get("name")
            for a in ((got2.ir or {}).get("attributes") or [])
            if isinstance(a, dict)
        }
        assert "Price" not in names2
