"""Прямые (без LLM) проверки создания РН и установки регистратора.

Цель — отделить баги metadata.create/update от поведения агента OpenCode.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from adapters.source.mdsparrow.constants import GAP_CODE
from adapters.source.xmlgen import EditOp
from adapters.source.xmlgen.resolve import resolve_jar, resolve_java
from core.metadata import (
    catalog_from_parts,
    create_metadata,
    get_metadata,
    update_metadata,
)
from tests.helpers_project import bootstrap_configuration_project


def _require_xmlgen() -> None:
    jar = resolve_jar()
    java = resolve_java()
    if not jar.found or not java.found:
        pytest.skip("xml-gen jar / Java недоступны")


@pytest.mark.integration
def test_xml_create_accumulation_register_with_dims_resources(tmp_path: Path) -> None:
    """XML: create РН с измерением/ресурсом + RegisterType Balance (ожидание xml-gen)."""
    _require_xmlgen()
    target = tmp_path / "shop"
    target.mkdir()
    assert bootstrap_configuration_project(target, name="Shop").status == "ok"

    cat = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="Catalog.Products",
            synonym="Товары",
        ),
    )
    assert cat.status == "ok", cat.diagnostics

    reg = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="AccumulationRegister.Stock",
            synonym="Остатки",
            dimension_specs=["Product:Ref:Catalog.Products:Товар"],
            resource_specs=["Qty:Number:15.2:Количество"],
        ),
    )
    assert reg.status == "ok", reg.diagnostics

    path = target / "src" / "cf" / "AccumulationRegisters" / "Stock.xml"
    assert path.is_file()
    text = path.read_text(encoding="utf-8-sig")
    assert "Product" in text or "Товар" in text
    assert "Qty" in text or "Количество" in text
    assert "<RegisterType>Balance</RegisterType>" in text, (
        "xml-gen не записал RegisterType=Balance — проверь DSL/defaults"
    )


@pytest.mark.integration
def test_xml_document_register_records_as_registrar(tmp_path: Path) -> None:
    """XML: metadata.update registerRecords на документе должен сохраниться."""
    _require_xmlgen()
    target = tmp_path / "shop"
    target.mkdir()
    assert bootstrap_configuration_project(target, name="Shop").status == "ok"

    assert (
        create_metadata(
            target,
            catalog_from_parts(qualified_name="Catalog.Products"),
        ).status
        == "ok"
    )
    assert (
        create_metadata(
            target,
            catalog_from_parts(
                qualified_name="AccumulationRegister.Stock",
                dimension_specs=["Product:Ref:Catalog.Products"],
                resource_specs=["Qty:Number:15.2"],
            ),
        ).status
        == "ok"
    )
    assert (
        create_metadata(
            target,
            catalog_from_parts(
                qualified_name="Document.GoodsReceipt",
                synonym="Оприходование",
                ts_specs=["Goods:Товары"],
                ts_attr_specs=[
                    "Goods.Product:Ref:Catalog.Products",
                    "Goods.Qty:Number:15.2",
                ],
            ),
        ).status
        == "ok"
    )

    upd = update_metadata(
        target,
        "Document.GoodsReceipt",
        [EditOp("modify-property", "registerRecords=AccumulationRegister.Stock")],
    )
    assert upd.status == "ok", upd.diagnostics

    doc = target / "src" / "cf" / "Documents" / "GoodsReceipt.xml"
    text = doc.read_text(encoding="utf-8-sig")
    assert "AccumulationRegister.Stock" in text
    # SteelMorgan/1c-agent-based-dev-framework#27: must be MDListType, not text node.
    assert 'xsi:type="xr:MDObjectRef"' in text
    assert "<xr:Item" in text
    assert re.search(
        r"<RegisterRecords>\s*<xr:Item[^>]*>AccumulationRegister\.Stock</xr:Item>",
        text,
        re.S,
    )

    # Flat text form breaks ibcmd XDTO import — build must succeed after rewrite.
    from adapters.platform import discover_environment
    from core.build import run_build

    discovery = discover_environment()
    if discovery.ibcmd.found:
        built = run_build(target)
        assert built.status == "ok", built.diagnostics

    got = get_metadata(target, "Document.GoodsReceipt")
    assert got.status == "ok", got.diagnostics


@pytest.mark.integration
def test_edt_register_records_gap_or_success(tmp_path: Path) -> None:
    """EDT: registerRecords — либо успех, либо явный 1CS010 (не silent no-op)."""
    from adapters.source.mdsparrow.resolve import resolve_jar as resolve_sparrow
    from adapters.source.mdsparrow.resolve import resolve_java as resolve_sparrow_java
    from core.source import run_convert

    spar = resolve_sparrow()
    spar_java = resolve_sparrow_java()
    if not spar.found or not spar_java.found:
        pytest.skip("md-sparrow / JDK 25+ недоступны")

    _require_xmlgen()
    target = tmp_path / "shop"
    target.mkdir()
    assert bootstrap_configuration_project(target, name="Shop").status == "ok"
    assert (
        create_metadata(
            target,
            catalog_from_parts(qualified_name="Catalog.Products"),
        ).status
        == "ok"
    )
    assert (
        create_metadata(
            target,
            catalog_from_parts(
                qualified_name="AccumulationRegister.Stock",
                dimension_specs=["Product:Ref:Catalog.Products"],
                resource_specs=["Qty:Number:15.2"],
            ),
        ).status
        == "ok"
    )
    assert (
        create_metadata(
            target,
            catalog_from_parts(qualified_name="Document.GoodsReceipt"),
        ).status
        == "ok"
    )

    # XML → EDT
    conv = run_convert(target, to="edt")
    if conv.status != "ok":
        pytest.skip(f"source.convert edt недоступен: {conv.to_payload()}")

    upd = update_metadata(
        target,
        "Document.GoodsReceipt",
        [EditOp("modify-property", "registerRecords=AccumulationRegister.Stock")],
    )
    # Known gap (#167): hard-fail 1CS010 is acceptable; silent success without .mdo write is not.
    if upd.status == "ok":
        mdo = next(
            (target / "src").rglob("Documents/GoodsReceipt/GoodsReceipt.mdo"),
            None,
        )
        assert mdo is not None and mdo.is_file()
        text = mdo.read_text(encoding="utf-8")
        assert "AccumulationRegister.Stock" in text, (
            "EDT update вернул ok, но registerRecords не в .mdo (silent no-op)"
        )
    else:
        payload = upd.to_payload()
        diags = payload.get("diagnostics") or upd.diagnostics or []
        codes: set[str] = set()
        for d in diags:
            if isinstance(d, dict):
                codes.add(str(d.get("code") or ""))
            else:
                codes.add(str(getattr(d, "code", "") or ""))
        assert GAP_CODE in codes, (
            f"ожидали {GAP_CODE} или успех с записью, получили {payload}"
        )
