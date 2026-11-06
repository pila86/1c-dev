"""Source Adapter contract tests (PRD §50 / ADR-032 / #158).

Общий набор capabilities для XML и EDT:
detect / inspect / read / write / validate / create / sync / convert.

Integration-кейсы без EDT CLI / md-sparrow JDK / xml-gen / md-reader — skip
с явными сообщениями (согласованы с doctor / CONTRIBUTING).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from adapters.source import (
    EDT_WRITE_KNOWN_GAPS,
    SOURCE_ADAPTER_CAPABILITIES,
    get_capabilities,
)
from adapters.source.capabilities import capabilities_payload
from adapters.source.edt import EdtSourceAdapter
from adapters.source.mdsparrow import GAP_CODE
from adapters.source.xml import (
    CODE_LAYOUT_NOT_XML,
    CODE_PATH_NOT_XML_ROOT,
    XmlSourceAdapter,
)
from adapters.source.xmlgen.edit import EditOp
from core.metadata import (
    catalog_from_parts,
    create_metadata,
    delete_metadata,
    list_metadata,
    update_metadata,
)
from core.source import run_convert
from tests.helpers_source_contract import (
    EDT_SPIKE,
    copy_edt_spike,
    require_edtcli,
    require_md_reader,
    require_mdsparrow,
    require_xmlgen,
    write_xml_contract_project,
)

REQUIRED_CAPS = (
    "detect",
    "inspect",
    "read",
    "write",
    "validate",
    "create",
    "sync",
    "convert",
    "incrementalSync",
)


@pytest.mark.parametrize("fmt", ["xml", "edt"])
def test_capability_matrix_matches_prd50(fmt: str) -> None:
    caps = get_capabilities(fmt)  # type: ignore[arg-type]
    assert set(caps) == set(REQUIRED_CAPS)
    assert caps["detect"] is True
    assert caps["inspect"] is True
    assert caps["read"] is True
    assert caps["write"] is True
    assert caps["validate"] is True
    assert caps["create"] is True
    assert caps["convert"] is True
    assert caps["sync"] is False  # вне M7
    assert caps["incrementalSync"] is None  # TBD


def test_xml_and_edt_capability_parity() -> None:
    """XML и EDT объявляют одинаковый M7-контракт (PRD §50 matrix)."""
    assert SOURCE_ADAPTER_CAPABILITIES["xml"] == SOURCE_ADAPTER_CAPABILITIES["edt"]


@pytest.mark.parametrize(
    ("adapter_cls", "fmt", "convert_to"),
    [
        (XmlSourceAdapter, "xml", ["edt"]),
        (EdtSourceAdapter, "edt", ["xml"]),
    ],
)
def test_adapter_capabilities_payload(
    adapter_cls: type[Any],
    fmt: str,
    convert_to: list[str],
) -> None:
    payload = adapter_cls().capabilities()
    assert payload == capabilities_payload(fmt)  # type: ignore[arg-type]
    assert payload["format"] == fmt
    assert payload["capabilities"]["convertTo"] == convert_to
    assert payload["capabilities"]["sync"] is False


def test_edt_write_known_gaps_documented() -> None:
    assert "number_precision_scale" in EDT_WRITE_KNOWN_GAPS
    assert "tabular_section_synonym" in EDT_WRITE_KNOWN_GAPS


# --- detect / inspect / validate (unit, без внешних инструментов) ---


def test_xml_contract_detect_inspect_validate(tmp_path: Path) -> None:
    root = write_xml_contract_project(tmp_path)
    source = root / "src" / "cf"
    adapter = XmlSourceAdapter()

    detected = adapter.detect(source)
    assert detected.is_xml is True
    assert detected.has_configuration_xml is True
    assert detected.code is None

    info = adapter.inspect(source)
    assert info.format == "xml"
    assert info.is_xml is True
    assert info.has_configuration_xml is True

    assert adapter.validate(source).is_xml is True


def test_xml_contract_detect_rejects_nested(tmp_path: Path) -> None:
    root = write_xml_contract_project(tmp_path)
    nested = root / "src" / "cf" / "Catalogs"
    detected = XmlSourceAdapter().detect(nested)
    assert detected.is_xml is False
    assert detected.code == CODE_PATH_NOT_XML_ROOT


def test_xml_contract_detect_empty(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    detected = XmlSourceAdapter().validate(empty)
    assert detected.is_xml is False
    assert detected.code == CODE_LAYOUT_NOT_XML


def test_edt_contract_detect_inspect_validate() -> None:
    adapter = EdtSourceAdapter()
    detected = adapter.detect(EDT_SPIKE)
    assert detected.is_edt is True
    assert detected.project_name == "EdtSpike"

    info = adapter.inspect(EDT_SPIKE)
    assert info.format == "edt"
    assert info.project_name == "EdtSpike"

    assert adapter.validate(EDT_SPIKE).is_edt is True


# --- read (integration: md-reader) ---


@pytest.mark.integration
def test_contract_read_xml(tmp_path: Path) -> None:
    require_md_reader()
    root = write_xml_contract_project(tmp_path)
    source = root / "src" / "cf"
    payload = XmlSourceAdapter().read("list", source)
    assert payload["status"] == "ok"
    qnames = {obj["qname"] for obj in payload["objects"]}
    assert "Catalog.Products" in qnames

    listed = list_metadata(root)
    assert listed.status == "ok"
    assert any(o.get("qname") == "Catalog.Products" for o in listed.objects)


@pytest.mark.integration
def test_contract_read_edt() -> None:
    require_md_reader()
    payload = EdtSourceAdapter().read("list", EDT_SPIKE)
    assert payload["status"] == "ok"
    qnames = {obj["qname"] for obj in payload["objects"]}
    assert "Catalog.Products" in qnames

    listed = list_metadata(EDT_SPIKE)
    assert listed.status == "ok"
    assert any(o.get("qname") == "Catalog.Products" for o in listed.objects)


# --- create / write (integration: xml-gen / md-sparrow) ---


@pytest.mark.integration
def test_contract_create_write_delete_xml(tmp_path: Path) -> None:
    require_xmlgen()
    root = write_xml_contract_project(tmp_path)

    created = create_metadata(
        root,
        catalog_from_parts(
            qualified_name="Catalog.Partners",
            synonym="Партнёры",
            attr_specs=["Article:String:50:Артикул"],
        ),
    )
    assert created.status == "ok", created.diagnostics
    partners = root / "src" / "cf" / "Catalogs" / "Partners.xml"
    assert partners.is_file()

    updated = update_metadata(
        root,
        "Catalog.Partners",
        [EditOp("add-attribute", "Comment:String(100)")],
    )
    assert updated.status == "ok", updated.diagnostics

    deleted = delete_metadata(root, "Catalog.Partners")
    assert deleted.status == "ok", deleted.diagnostics
    assert not partners.exists()


@pytest.mark.integration
def test_contract_create_write_delete_edt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_mdsparrow(monkeypatch)
    target = copy_edt_spike(tmp_path)
    partners = target / "src" / "Catalogs" / "Partners" / "Partners.mdo"

    created = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="Catalog.Partners",
            synonym="Партнёры",
            attr_specs=["Article:String:50:Артикул"],
        ),
    )
    assert created.status == "ok", created.diagnostics
    assert partners.is_file()
    text = partners.read_text(encoding="utf-8")
    assert "Партнёры" in text
    assert "<name>Article</name>" in text

    updated = update_metadata(
        target,
        "Catalog.Partners",
        [EditOp("add-attribute", "Comment:String(100)")],
    )
    assert updated.status == "ok", updated.diagnostics
    assert "<name>Comment</name>" in partners.read_text(encoding="utf-8")

    deleted = delete_metadata(target, "Catalog.Partners")
    assert deleted.status == "ok", deleted.diagnostics
    assert not partners.exists()


@pytest.mark.integration
def test_contract_edt_known_gap_number_precision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Number precision — известный gap path D → warning 1CS010 (не fail)."""
    require_mdsparrow(monkeypatch)
    target = copy_edt_spike(tmp_path)

    created = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="Catalog.GapNum",
            synonym="GapNum",
            attr_specs=["Price:Number:15.2:Цена"],
        ),
    )
    assert created.status == "ok", created.diagnostics
    # Gap-warning 1CS010 опционален (зависит от md-sparrow); create не должен падать.
    assert all(
        d.get("severity") != "error" or d.get("code") != GAP_CODE
        for d in created.diagnostics
    )
    assert GAP_CODE == "1CS010"


# --- convert (integration: 1cedtcli) ---


@pytest.mark.integration
def test_contract_convert_edt_to_xml_and_back(tmp_path: Path) -> None:
    require_edtcli()
    root = copy_edt_spike(tmp_path)

    to_xml = run_convert(root, to="xml")
    assert to_xml.status == "ok", to_xml.diagnostics
    assert (root / "Configuration.xml").is_file()
    assert XmlSourceAdapter().detect(root).is_xml is True

    to_edt = run_convert(root, to="edt")
    assert to_edt.status == "ok", to_edt.diagnostics
    assert EdtSourceAdapter().detect(root).is_edt is True
