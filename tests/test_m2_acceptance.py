"""M2 acceptance: Document+ТЧ → update → Enum+регистр → read → delete → build/check (#27)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from adapters.platform import discover_environment
from adapters.platform_ibcmd.constants import IB_MARKER
from adapters.source.mdclasses.resolve import resolve_jar as resolve_md_jar
from adapters.source.mdclasses.resolve import resolve_java as resolve_md_java
from adapters.source.xmlgen import EditOp
from adapters.source.xmlgen.resolve import resolve_jar, resolve_java
from core.build import run_build
from core.check import run_check
from core.metadata import (
    catalog_from_parts,
    create_metadata,
    delete_metadata,
    find_metadata,
    get_metadata,
    list_metadata,
    update_metadata,
)
from core.project import init_project


@pytest.mark.integration
def test_m2_acceptance_document_enum_register_delete(tmp_path: Path) -> None:
    """Full M2 flow; skip if platform, xml-gen or md-reader unavailable."""
    jar = resolve_jar()
    java = resolve_java()
    if not jar.found or not java.found:
        pytest.skip("xml-gen jar / Java 17+ недоступны (запустите scripts/fetch-xml-gen.sh)")

    md_jar = resolve_md_jar()
    md_java = resolve_md_java()
    if not md_jar.found or not md_java.found:
        pytest.skip(
            "md-reader jar / Java 21+ недоступны (запустите scripts/fetch-md-reader.sh)"
        )

    discovery = discover_environment()
    if not discovery.ibcmd.found or discovery.ibcmd.path is None:
        pytest.skip("ibcmd не найден — M2 acceptance пропущен")

    target = tmp_path / "shop"
    target.mkdir()
    init = init_project(target, project_type="configuration", name="Shop")
    assert init.status == "ok", init.to_payload()

    # Ref-target catalog
    cat = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="Catalog.Products",
            synonym="Товары",
            attr_specs=["Article:String:50:Артикул"],
        ),
    )
    assert cat.status == "ok", cat.diagnostics

    # Document with attributes + tabular section
    doc = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="Document.Sales",
            synonym="Продажи",
            attr_specs=[
                "Comment:String:100:Комментарий",
                "Counterparty:Ref:Catalog.Products:Контрагент",
            ],
            ts_specs=["Products:Товары"],
            ts_attr_specs=[
                "Products.Item:Ref:Catalog.Products:Товар",
                "Products.Qty:Number:15.3:Количество",
            ],
        ),
    )
    assert doc.status == "ok", doc.diagnostics
    sales = target / "src" / "cf" / "Documents" / "Sales.xml"
    assert sales.is_file()
    sales_text = sales.read_text(encoding="utf-8-sig")
    assert "Comment" in sales_text
    assert "Products" in sales_text
    assert "Qty" in sales_text

    # Update: add ts-attribute, then duplicate → ok + warning, source intact
    added = update_metadata(
        target,
        "Document.Sales",
        [EditOp("add-ts-attribute", "Products.Price:Number(15,2)")],
    )
    assert added.status == "ok", added.diagnostics
    assert "Price" in sales.read_text(encoding="utf-8-sig")

    checksum = hashlib.sha256(sales.read_bytes()).hexdigest()
    dup = update_metadata(
        target,
        "Document.Sales",
        [EditOp("add-ts-attribute", "Products.Price:Number(15,2)")],
    )
    assert dup.status == "ok", dup.diagnostics
    assert any(d.get("severity") == "warning" for d in dup.diagnostics)
    assert hashlib.sha256(sales.read_bytes()).hexdigest() == checksum

    # Enum + InformationRegister
    enum = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="Enum.OrderStatuses",
            synonym="СтатусыЗаказа",
            value_specs=["New:Новый", "Done:Выполнен"],
        ),
    )
    assert enum.status == "ok", enum.diagnostics

    info = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="InformationRegister.Prices",
            synonym="Цены",
            dimension_specs=["Product:Ref:Catalog.Products:Товар"],
            resource_specs=["Price:Number:15.2:Цена"],
        ),
    )
    assert info.status == "ok", info.diagnostics

    cfg = (target / "src" / "cf" / "Configuration.xml").read_text(encoding="utf-8-sig")
    assert "<Document>Sales</Document>" in cfg
    assert "<Enum>OrderStatuses</Enum>" in cfg
    assert "<InformationRegister>Prices</InformationRegister>" in cfg

    # Read: list / get / find
    listed = list_metadata(target)
    assert listed.status == "ok", listed.diagnostics
    qnames = {o["qname"] for o in listed.objects}
    assert "Document.Sales" in qnames
    assert "Enum.OrderStatuses" in qnames
    assert "InformationRegister.Prices" in qnames
    assert "Catalog.Products" in qnames

    got = get_metadata(target, "Document.Sales")
    assert got.status == "ok", got.diagnostics
    assert got.ir is not None
    assert got.ir.get("type") == "Document"
    assert got.ir.get("name") == "Sales"
    sections = {
        s.get("name"): s
        for s in (got.ir.get("tabularSections") or [])
        if isinstance(s, dict)
    }
    assert "Products" in sections
    ts_attrs = {
        a.get("name"): a
        for a in (sections["Products"].get("attributes") or [])
        if isinstance(a, dict)
    }
    assert "Qty" in ts_attrs
    assert "Price" in ts_attrs

    found = find_metadata(target, "Продажи")
    assert found.status == "ok", found.diagnostics
    assert any(o.get("qname") == "Document.Sales" for o in found.objects)

    # Delete Enum (no Ref from Document/register — safe for build/check)
    enum_xml = target / "src" / "cf" / "Enums" / "OrderStatuses.xml"
    assert enum_xml.is_file()
    deleted = delete_metadata(target, "Enum.OrderStatuses")
    assert deleted.status == "ok", deleted.diagnostics
    assert deleted.deleted
    assert not enum_xml.is_file()
    cfg_after = (target / "src" / "cf" / "Configuration.xml").read_text(
        encoding="utf-8-sig"
    )
    assert "<Enum>OrderStatuses</Enum>" not in cfg_after

    listed_after = list_metadata(target)
    assert listed_after.status == "ok", listed_after.diagnostics
    qnames_after = {o["qname"] for o in listed_after.objects}
    assert "Enum.OrderStatuses" not in qnames_after
    assert "Document.Sales" in qnames_after

    got_gone = get_metadata(target, "Enum.OrderStatuses")
    assert got_gone.status == "error"
    assert any(d.get("code") == "1CM008" for d in got_gone.diagnostics)

    again = delete_metadata(target, "Enum.OrderStatuses")
    assert again.status == "error"
    assert any(d.get("code") == "1CM008" for d in again.diagnostics)

    build = run_build(target)
    assert build.status == "ok", build.to_payload()
    assert (target / ".runtime" / "ib" / IB_MARKER).is_file()

    check = run_check(target)
    assert check.status == "ok", check.to_payload()
