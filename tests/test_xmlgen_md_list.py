"""Unit: MDListType rewrite for RegisterRecords (framework#27 workaround)."""

from __future__ import annotations

from pathlib import Path

from adapters.source.xmlgen.md_list import (
    ops_touch_md_list,
    rewrite_md_list_properties,
)


def test_ops_touch_md_list() -> None:
    assert ops_touch_md_list(["RegisterRecords=AccumulationRegister.Stock"])
    assert ops_touch_md_list(["registerRecords=AccumulationRegister.Stock"])
    assert ops_touch_md_list(["Synonym=Hi"]) is False


def test_rewrite_flat_register_records(tmp_path: Path) -> None:
    xml = tmp_path / "Doc.xml"
    xml.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses"
	xmlns:xr="http://v8.1c.ru/8.3/xcf/readable"
	xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
	version="2.17">
	<Document>
		<Properties>
			<RegisterRecords>AccumulationRegister.Stock</RegisterRecords>
		</Properties>
	</Document>
</MetaDataObject>
""",
        encoding="utf-8",
    )
    assert rewrite_md_list_properties(xml) is True
    text = xml.read_text(encoding="utf-8")
    assert "<xr:Item" in text
    assert 'xsi:type="xr:MDObjectRef"' in text
    assert "AccumulationRegister.Stock" in text
    assert "<RegisterRecords>AccumulationRegister.Stock</RegisterRecords>" not in text
    # idempotent
    assert rewrite_md_list_properties(xml) is False


def test_rewrite_skips_already_correct(tmp_path: Path) -> None:
    xml = tmp_path / "Doc.xml"
    xml.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses"
	xmlns:xr="http://v8.1c.ru/8.3/xcf/readable"
	xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
	<Document>
		<Properties>
			<RegisterRecords>
				<xr:Item xsi:type="xr:MDObjectRef">AccumulationRegister.Stock</xr:Item>
			</RegisterRecords>
		</Properties>
	</Document>
</MetaDataObject>
""",
        encoding="utf-8",
    )
    assert rewrite_md_list_properties(xml) is False
