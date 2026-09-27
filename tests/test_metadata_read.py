"""Tests for metadata.list / get / find (ADR-012)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from adapters.source.mdclasses.resolve import resolve_jar, resolve_java
from cli.main import app
from core.exit_codes import SUCCESS
from core.metadata import find_metadata, get_metadata, list_metadata
from core.project import init_project

runner = CliRunner()


def test_list_metadata_mock(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    init = init_project(target, project_type="configuration", name="Shop")
    assert init.status == "ok"

    def fake_read(command: str, source_dir: Path, args: tuple[str, ...]) -> dict[str, Any]:
        assert command == "list"
        assert source_dir == (target / "src" / "cf").resolve()
        return {
            "status": "ok",
            "objects": [
                {
                    "type": "Language",
                    "name": "Русский",
                    "qname": "Language.Русский",
                    "synonym": "Русский",
                },
                {
                    "type": "Catalog",
                    "name": "Products",
                    "qname": "Catalog.Products",
                    "synonym": "Товары",
                },
            ],
        }

    result = list_metadata(target, read_fn=fake_read)
    assert result.status == "ok"
    assert len(result.objects) == 2
    assert result.objects[1]["qname"] == "Catalog.Products"


def test_get_metadata_mock(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")

    def fake_read(command: str, source_dir: Path, args: tuple[str, ...]) -> dict[str, Any]:
        assert command == "get"
        assert args == ("Catalog.Products",)
        return {
            "status": "ok",
            "object": {
                "type": "Catalog",
                "name": "Products",
                "qname": "Catalog.Products",
                "synonym": "Товары",
                "attributes": [
                    {
                        "name": "Article",
                        "type": "String",
                        "length": 50,
                        "synonym": "Артикул",
                    }
                ],
                "tabularSections": [],
            },
        }

    result = get_metadata(target, "Catalog.Products", read_fn=fake_read)
    assert result.status == "ok"
    assert result.object == "Catalog.Products"
    assert result.ir is not None
    assert result.ir["attributes"][0]["name"] == "Article"


def test_find_metadata_mock(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")

    def fake_read(command: str, source_dir: Path, args: tuple[str, ...]) -> dict[str, Any]:
        assert command == "find"
        assert args == ("Товар",)
        return {
            "status": "ok",
            "objects": [
                {
                    "type": "Catalog",
                    "name": "Products",
                    "qname": "Catalog.Products",
                    "synonym": "Товары",
                }
            ],
        }

    result = find_metadata(target, "Товар", read_fn=fake_read)
    assert result.status == "ok"
    assert result.objects[0]["synonym"] == "Товары"


def test_list_missing_jar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")
    monkeypatch.delenv("ONEC_MDREADER_JAR", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "empty-cache"))
    result = list_metadata(target)
    assert result.status == "error"
    assert any(d.get("code") == "1CM006" for d in result.diagnostics)


def test_get_not_found_mock(tmp_path: Path) -> None:
    from adapters.source.mdclasses import MdReaderError

    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")

    def fake_read(command: str, source_dir: Path, args: tuple[str, ...]) -> dict[str, Any]:
        raise MdReaderError("Объект не найден: Catalog.Missing", code="1CM008")

    result = get_metadata(target, "Catalog.Missing", read_fn=fake_read)
    assert result.status == "error"
    assert any(d.get("code") == "1CM008" for d in result.diagnostics)


def test_cli_list_mock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")
    monkeypatch.chdir(target)

    def fake_list(start: Path | None = None, *, read_fn: Any = None) -> Any:
        from core.metadata.result import MetadataResult

        return MetadataResult(
            status="ok",
            root=target,
            source_path=target / "src" / "cf",
            objects=[
                {
                    "type": "Language",
                    "name": "Русский",
                    "qname": "Language.Русский",
                }
            ],
        )

    monkeypatch.setattr("cli.metadata.list_metadata", fake_list)
    result = runner.invoke(app, ["metadata", "list", "--output", "json"])
    assert result.exit_code == SUCCESS, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["objects"][0]["qname"] == "Language.Русский"


def test_get_common_module_flags_mock(tmp_path: Path) -> None:
    """Smoke: md-reader full IR for CommonModule projects context flags (#61)."""
    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")

    def fake_read(command: str, source_dir: Path, args: tuple[str, ...]) -> dict[str, Any]:
        assert command == "get"
        assert args == ("CommonModule.SalesServer",)
        return {
            "status": "ok",
            "object": {
                "type": "CommonModule",
                "name": "SalesServer",
                "qname": "CommonModule.SalesServer",
                "synonym": "ПродажиСервер",
                "server": True,
                "clientManagedApplication": False,
                "clientOrdinaryApplication": False,
                "serverCall": True,
                "externalConnection": False,
                "privileged": False,
                "global": False,
                "returnValuesReuse": "DontUse",
            },
        }

    result = get_metadata(target, "CommonModule.SalesServer", read_fn=fake_read)
    assert result.status == "ok"
    assert result.object == "CommonModule.SalesServer"
    assert result.ir is not None
    assert result.ir["server"] is True
    assert result.ir["serverCall"] is True
    assert result.ir["clientManagedApplication"] is False
    assert result.ir["returnValuesReuse"] == "DontUse"


@pytest.mark.integration
def test_common_module_get_flags_roundtrip(tmp_path: Path) -> None:
    """create → get flags → update set-flag → get (#61)."""
    from adapters.source.xmlgen import EditOp
    from adapters.source.xmlgen.resolve import resolve_jar as resolve_xmlgen
    from adapters.source.xmlgen.resolve import resolve_java as resolve_java_xml
    from core.metadata import catalog_from_parts, create_metadata, update_metadata

    java = resolve_java()
    jar = resolve_jar()
    if not java.found or not jar.found:
        pytest.skip(
            "md-reader jar / Java 21+ недоступны (запустите scripts/fetch-md-reader.sh)"
        )
    xmlgen = resolve_xmlgen()
    if not xmlgen.found or not resolve_java_xml().found:
        pytest.skip("xml-gen jar / Java 17+ недоступны (запустите scripts/fetch-xml-gen.sh)")

    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")

    created = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="CommonModule.SalesServer",
            synonym="ПродажиСервер",
            server=True,
            server_call=False,
        ),
    )
    assert created.status == "ok", created.diagnostics

    got = get_metadata(target, "CommonModule.SalesServer")
    assert got.status == "ok", got.diagnostics
    assert got.ir is not None
    assert got.ir["type"] == "CommonModule"
    assert got.ir["name"] == "SalesServer"
    assert got.ir["server"] is True
    assert got.ir["serverCall"] is False
    assert got.ir["clientManagedApplication"] is False
    assert got.ir["clientOrdinaryApplication"] is False
    assert got.ir["externalConnection"] is False
    assert got.ir["privileged"] is False
    assert got.ir["global"] is False
    assert got.ir["returnValuesReuse"] == "DontUse"

    updated = update_metadata(
        target,
        "CommonModule.SalesServer",
        [
            EditOp("set-flag", "serverCall=true"),
            EditOp("set-flag", "client=true"),
            EditOp("set-flag", "returnValuesReuse=DuringRequest"),
        ],
    )
    assert updated.status == "ok", updated.diagnostics

    got2 = get_metadata(target, "CommonModule.SalesServer")
    assert got2.status == "ok", got2.diagnostics
    assert got2.ir is not None
    assert got2.ir["server"] is True
    assert got2.ir["serverCall"] is True
    assert got2.ir["clientManagedApplication"] is True
    assert got2.ir["returnValuesReuse"] == "DuringRequest"


def test_get_subsystem_full_ir_mock(tmp_path: Path) -> None:
    """Smoke: md-reader full IR for Subsystem content/children (#62)."""
    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")

    def fake_read(command: str, source_dir: Path, args: tuple[str, ...]) -> dict[str, Any]:
        assert command == "get"
        assert args == ("Subsystem.Main",)
        return {
            "status": "ok",
            "object": {
                "type": "Subsystem",
                "name": "Main",
                "qname": "Subsystem.Main",
                "synonym": "Главная",
                "content": ["Catalog.Products"],
                "children": ["Sales"],
                "includeInCommandInterface": True,
            },
        }

    result = get_metadata(target, "Subsystem.Main", read_fn=fake_read)
    assert result.status == "ok"
    assert result.object == "Subsystem.Main"
    assert result.ir is not None
    assert result.ir["content"] == ["Catalog.Products"]
    assert result.ir["children"] == ["Sales"]
    assert result.ir["includeInCommandInterface"] is True


def _local_md_reader_jar() -> Path | None:
    """Prefer freshly built md-reader jar from tools/ (Report/DataProcessor full IR)."""
    built = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "md-reader"
        / "build"
        / "libs"
        / "md-reader.jar"
    )
    return built if built.is_file() else None


@pytest.mark.integration
def test_subsystem_get_full_ir_roundtrip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create → get full IR → update → get → delete (#62)."""
    from adapters.source.xmlgen import EditOp
    from adapters.source.xmlgen.resolve import resolve_jar as resolve_xmlgen
    from adapters.source.xmlgen.resolve import resolve_java as resolve_java_xml
    from core.metadata import (
        catalog_from_parts,
        create_metadata,
        delete_metadata,
        update_metadata,
    )

    local_jar = _local_md_reader_jar()
    if local_jar is not None:
        monkeypatch.setenv("ONEC_MDREADER_JAR", str(local_jar))

    java = resolve_java()
    jar = resolve_jar()
    if not java.found or not jar.found:
        pytest.skip(
            "md-reader jar / Java 21+ недоступны (запустите scripts/fetch-md-reader.sh)"
        )
    xmlgen = resolve_xmlgen()
    if not xmlgen.found or not resolve_java_xml().found:
        pytest.skip("xml-gen jar / Java 17+ недоступны (запустите scripts/fetch-xml-gen.sh)")

    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")

    cat = create_metadata(
        target,
        catalog_from_parts(qualified_name="Catalog.Products", synonym="Товары"),
    )
    assert cat.status == "ok", cat.diagnostics

    created = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="Subsystem.Main",
            synonym="Главная",
            include_in_command_interface=True,
        ),
    )
    assert created.status == "ok", created.diagnostics

    got = get_metadata(target, "Subsystem.Main")
    assert got.status == "ok", got.diagnostics
    assert got.ir is not None
    assert got.ir["type"] == "Subsystem"
    assert got.ir["name"] == "Main"
    assert got.ir.get("content") == []
    assert got.ir.get("children") == []
    assert got.ir.get("includeInCommandInterface") is True

    updated = update_metadata(
        target,
        "Subsystem.Main",
        [
            EditOp("add-content", "Catalog.Products"),
            EditOp("add-child", "Sales"),
            EditOp("set-property", "IncludeInCommandInterface=false"),
        ],
    )
    assert updated.status == "ok", updated.diagnostics

    got2 = get_metadata(target, "Subsystem.Main")
    assert got2.status == "ok", got2.diagnostics
    assert got2.ir is not None
    assert "Catalog.Products" in (got2.ir.get("content") or [])
    assert "Sales" in (got2.ir.get("children") or [])
    assert got2.ir.get("includeInCommandInterface") is False

    deleted = delete_metadata(target, "Subsystem.Main")
    assert deleted.status == "ok", deleted.diagnostics
    assert not (target / "src" / "cf" / "Subsystems" / "Main.xml").is_file()
    cfg = (target / "src" / "cf" / "Configuration.xml").read_text(encoding="utf-8-sig")
    assert "<Subsystem>Main</Subsystem>" not in cfg


def test_get_constant_and_defined_type_full_ir_mock(tmp_path: Path) -> None:
    """Smoke: md-reader full IR for Constant / DefinedType (#63)."""
    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")

    def fake_read_const(
        command: str, source_dir: Path, args: tuple[str, ...]
    ) -> dict[str, Any]:
        assert command == "get"
        assert args == ("Constant.VATRate",)
        return {
            "status": "ok",
            "object": {
                "type": "Constant",
                "name": "VATRate",
                "qname": "Constant.VATRate",
                "synonym": "СтавкаНДС",
                "valueType": {"type": "Number", "precision": 5, "scale": 2},
            },
        }

    result = get_metadata(target, "Constant.VATRate", read_fn=fake_read_const)
    assert result.status == "ok"
    assert result.ir is not None
    assert result.ir["valueType"]["type"] == "Number"
    assert result.ir["valueType"]["precision"] == 5

    def fake_read_defined(
        command: str, source_dir: Path, args: tuple[str, ...]
    ) -> dict[str, Any]:
        assert args == ("DefinedType.MoneyCode",)
        return {
            "status": "ok",
            "object": {
                "type": "DefinedType",
                "name": "MoneyCode",
                "qname": "DefinedType.MoneyCode",
                "valueTypes": [
                    {"type": "String", "length": 50},
                    {"type": "Number", "precision": 10, "scale": 0},
                ],
            },
        }

    result2 = get_metadata(target, "DefinedType.MoneyCode", read_fn=fake_read_defined)
    assert result2.status == "ok"
    assert result2.ir is not None
    assert len(result2.ir["valueTypes"]) == 2


def test_get_report_and_dataprocessor_full_ir_mock(tmp_path: Path) -> None:
    """Smoke: md-reader full IR for Report / DataProcessor (#64)."""
    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")

    def fake_read_report(
        command: str, source_dir: Path, args: tuple[str, ...]
    ) -> dict[str, Any]:
        assert command == "get"
        assert args == ("Report.Sales",)
        return {
            "status": "ok",
            "object": {
                "type": "Report",
                "name": "Sales",
                "qname": "Report.Sales",
                "synonym": "Продажи",
                "attributes": [{"name": "Period", "type": "Date"}],
                "tabularSections": [
                    {
                        "name": "Lines",
                        "attributes": [
                            {"name": "Amount", "type": "Number", "precision": 15, "scale": 2}
                        ],
                    }
                ],
            },
        }

    result = get_metadata(target, "Report.Sales", read_fn=fake_read_report)
    assert result.status == "ok"
    assert result.ir is not None
    assert result.ir["type"] == "Report"
    assert result.ir["attributes"][0]["name"] == "Period"
    assert result.ir["tabularSections"][0]["name"] == "Lines"

    def fake_read_processor(
        command: str, source_dir: Path, args: tuple[str, ...]
    ) -> dict[str, Any]:
        assert args == ("DataProcessor.ImportData",)
        return {
            "status": "ok",
            "object": {
                "type": "DataProcessor",
                "name": "ImportData",
                "qname": "DataProcessor.ImportData",
                "attributes": [{"name": "Path", "type": "String", "length": 200}],
                "tabularSections": [],
            },
        }

    result2 = get_metadata(
        target, "DataProcessor.ImportData", read_fn=fake_read_processor
    )
    assert result2.status == "ok"
    assert result2.ir is not None
    assert result2.ir["attributes"][0]["length"] == 200


def test_get_scheduled_job_and_event_subscription_full_ir_mock(tmp_path: Path) -> None:
    """Smoke: md-reader full IR for ScheduledJob / EventSubscription (#65)."""
    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")

    def fake_read_job(
        command: str, source_dir: Path, args: tuple[str, ...]
    ) -> dict[str, Any]:
        assert command == "get"
        assert args == ("ScheduledJob.Cleanup",)
        return {
            "status": "ok",
            "object": {
                "type": "ScheduledJob",
                "name": "Cleanup",
                "qname": "ScheduledJob.Cleanup",
                "synonym": "Очистка",
                "methodName": "CommonModule.Jobs.Cleanup",
                "use": True,
                "description": "Nightly",
                "key": "cleanup",
                "predefined": False,
                "restartCountOnFailure": 5,
                "restartIntervalOnFailure": 20,
            },
        }

    result = get_metadata(target, "ScheduledJob.Cleanup", read_fn=fake_read_job)
    assert result.status == "ok"
    assert result.ir is not None
    assert result.ir["methodName"] == "CommonModule.Jobs.Cleanup"
    assert result.ir["use"] is True
    assert result.ir["restartCountOnFailure"] == 5

    def fake_read_sub(
        command: str, source_dir: Path, args: tuple[str, ...]
    ) -> dict[str, Any]:
        assert args == ("EventSubscription.ProductsBeforeWrite",)
        return {
            "status": "ok",
            "object": {
                "type": "EventSubscription",
                "name": "ProductsBeforeWrite",
                "qname": "EventSubscription.ProductsBeforeWrite",
                "handler": "CommonModule.Jobs.BeforeWrite",
                "event": "BeforeWrite",
                "source": ["Catalog.Products"],
            },
        }

    result2 = get_metadata(
        target, "EventSubscription.ProductsBeforeWrite", read_fn=fake_read_sub
    )
    assert result2.status == "ok"
    assert result2.ir is not None
    assert result2.ir["handler"] == "CommonModule.Jobs.BeforeWrite"
    assert result2.ir["event"] == "BeforeWrite"
    assert result2.ir["source"] == ["Catalog.Products"]


@pytest.mark.integration
def test_constant_defined_type_get_update_delete_roundtrip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create → get full IR → update synonym → get → delete (#63)."""
    from adapters.source.xmlgen import EditOp
    from adapters.source.xmlgen.resolve import resolve_jar as resolve_xmlgen
    from adapters.source.xmlgen.resolve import resolve_java as resolve_java_xml
    from core.metadata import (
        catalog_from_parts,
        create_metadata,
        delete_metadata,
        update_metadata,
    )

    local_jar = _local_md_reader_jar()
    if local_jar is not None:
        monkeypatch.setenv("ONEC_MDREADER_JAR", str(local_jar))

    java = resolve_java()
    jar = resolve_jar()
    if not java.found or not jar.found:
        pytest.skip(
            "md-reader jar / Java 21+ недоступны (запустите scripts/fetch-md-reader.sh)"
        )
    xmlgen = resolve_xmlgen()
    if not xmlgen.found or not resolve_java_xml().found:
        pytest.skip("xml-gen jar / Java 17+ недоступны (запустите scripts/fetch-xml-gen.sh)")

    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")

    created = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="Constant.VATRate",
            synonym="СтавкаНДС",
            value_type_specs=["Number:5.2"],
        ),
    )
    assert created.status == "ok", created.diagnostics

    got = get_metadata(target, "Constant.VATRate")
    assert got.status == "ok", got.diagnostics
    assert got.ir is not None
    assert got.ir["type"] == "Constant"
    assert got.ir["name"] == "VATRate"
    assert got.ir["valueType"]["type"] == "Number"
    assert got.ir["valueType"]["precision"] == 5
    assert got.ir["valueType"]["scale"] == 2

    updated = update_metadata(
        target,
        "Constant.VATRate",
        [EditOp("modify-property", "Synonym=НоваяСтавка")],
    )
    assert updated.status == "ok", updated.diagnostics

    got2 = get_metadata(target, "Constant.VATRate")
    assert got2.status == "ok", got2.diagnostics
    assert got2.ir is not None
    assert got2.ir.get("synonym") == "НоваяСтавка"

    defined = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="DefinedType.MoneyCode",
            synonym="КодДенег",
            value_type_specs=["String:50"],
        ),
    )
    assert defined.status == "ok", defined.diagnostics

    got_d = get_metadata(target, "DefinedType.MoneyCode")
    assert got_d.status == "ok", got_d.diagnostics
    assert got_d.ir is not None
    assert got_d.ir["type"] == "DefinedType"
    types = got_d.ir.get("valueTypes") or [got_d.ir.get("valueType")]
    assert types[0]["type"] == "String"
    assert types[0]["length"] == 50

    updated_d = update_metadata(
        target,
        "DefinedType.MoneyCode",
        [EditOp("modify-property", "Synonym=КодСуммы")],
    )
    assert updated_d.status == "ok", updated_d.diagnostics

    deleted_c = delete_metadata(target, "Constant.VATRate")
    assert deleted_c.status == "ok", deleted_c.diagnostics
    assert not (target / "src" / "cf" / "Constants" / "VATRate.xml").is_file()

    deleted_d = delete_metadata(target, "DefinedType.MoneyCode")
    assert deleted_d.status == "ok", deleted_d.diagnostics
    assert not (target / "src" / "cf" / "DefinedTypes" / "MoneyCode.xml").is_file()

    cfg = (target / "src" / "cf" / "Configuration.xml").read_text(encoding="utf-8-sig")
    assert "<Constant>VATRate</Constant>" not in cfg
    assert "<DefinedType>MoneyCode</DefinedType>" not in cfg


@pytest.mark.integration
def test_report_dataprocessor_get_update_delete_roundtrip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create (attr/TS) → get full IR → update attr/TS → delete (#64)."""
    from adapters.source.xmlgen import EditOp
    from adapters.source.xmlgen.resolve import resolve_jar as resolve_xmlgen
    from adapters.source.xmlgen.resolve import resolve_java as resolve_java_xml
    from core.metadata import (
        catalog_from_parts,
        create_metadata,
        delete_metadata,
        update_metadata,
    )

    local_jar = _local_md_reader_jar()
    if local_jar is not None:
        monkeypatch.setenv("ONEC_MDREADER_JAR", str(local_jar))

    java = resolve_java()
    jar = resolve_jar()
    if not java.found or not jar.found:
        pytest.skip(
            "md-reader jar / Java 21+ недоступны (запустите scripts/fetch-md-reader.sh)"
        )
    xmlgen = resolve_xmlgen()
    if not xmlgen.found or not resolve_java_xml().found:
        pytest.skip("xml-gen jar / Java 17+ недоступны (запустите scripts/fetch-xml-gen.sh)")

    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")

    created = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="Report.Sales",
            synonym="Продажи",
            attr_specs=["Period:Date:Период"],
            ts_specs=["Lines:Строки"],
            ts_attr_specs=["Lines.Amount:Number:15.2:Сумма"],
        ),
    )
    assert created.status == "ok", created.diagnostics

    got = get_metadata(target, "Report.Sales")
    assert got.status == "ok", got.diagnostics
    assert got.ir is not None
    assert got.ir["type"] == "Report"
    assert got.ir["name"] == "Sales"
    attrs = {
        a.get("name"): a
        for a in (got.ir.get("attributes") or [])
        if isinstance(a, dict)
    }
    assert "Period" in attrs
    assert attrs["Period"].get("type") == "Date"
    sections = {
        s.get("name"): s
        for s in (got.ir.get("tabularSections") or [])
        if isinstance(s, dict)
    }
    assert "Lines" in sections
    ts_attrs = {
        a.get("name"): a
        for a in (sections["Lines"].get("attributes") or [])
        if isinstance(a, dict)
    }
    assert "Amount" in ts_attrs
    assert ts_attrs["Amount"].get("type") == "Number"

    updated = update_metadata(
        target,
        "Report.Sales",
        [
            EditOp("add-attribute", "Cutoff:Number(10,2)"),
            EditOp("add-ts-attribute", "Lines.Qty:Number(15,3)"),
            EditOp("modify-property", "Synonym=ОтчётПродажи"),
        ],
    )
    assert updated.status == "ok", updated.diagnostics

    got2 = get_metadata(target, "Report.Sales")
    assert got2.status == "ok", got2.diagnostics
    assert got2.ir is not None
    assert got2.ir.get("synonym") == "ОтчётПродажи"
    attrs2 = {
        a.get("name"): a
        for a in (got2.ir.get("attributes") or [])
        if isinstance(a, dict)
    }
    assert "Cutoff" in attrs2
    sections2 = {
        s.get("name"): s
        for s in (got2.ir.get("tabularSections") or [])
        if isinstance(s, dict)
    }
    ts_attrs2 = {
        a.get("name"): a
        for a in (sections2["Lines"].get("attributes") or [])
        if isinstance(a, dict)
    }
    assert "Qty" in ts_attrs2

    processor = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="DataProcessor.ImportData",
            synonym="Загрузка",
            attr_specs=["Path:String:200:Путь"],
        ),
    )
    assert processor.status == "ok", processor.diagnostics

    got_p = get_metadata(target, "DataProcessor.ImportData")
    assert got_p.status == "ok", got_p.diagnostics
    assert got_p.ir is not None
    assert got_p.ir["type"] == "DataProcessor"
    p_attrs = {
        a.get("name"): a
        for a in (got_p.ir.get("attributes") or [])
        if isinstance(a, dict)
    }
    assert "Path" in p_attrs
    assert p_attrs["Path"].get("type") == "String"
    assert p_attrs["Path"].get("length") == 200

    updated_p = update_metadata(
        target,
        "DataProcessor.ImportData",
        [
            EditOp("add-attribute", "DryRun:Boolean"),
            EditOp("modify-attribute", "Path: synonym=ПутьКФайлу"),
        ],
    )
    assert updated_p.status == "ok", updated_p.diagnostics

    got_p2 = get_metadata(target, "DataProcessor.ImportData")
    assert got_p2.status == "ok", got_p2.diagnostics
    assert got_p2.ir is not None
    p_attrs2 = {
        a.get("name"): a
        for a in (got_p2.ir.get("attributes") or [])
        if isinstance(a, dict)
    }
    assert "DryRun" in p_attrs2
    assert p_attrs2["Path"].get("synonym") == "ПутьКФайлу"

    deleted_r = delete_metadata(target, "Report.Sales")
    assert deleted_r.status == "ok", deleted_r.diagnostics
    assert not (target / "src" / "cf" / "Reports" / "Sales.xml").is_file()

    deleted_p = delete_metadata(target, "DataProcessor.ImportData")
    assert deleted_p.status == "ok", deleted_p.diagnostics
    assert not (target / "src" / "cf" / "DataProcessors" / "ImportData.xml").is_file()

    cfg = (target / "src" / "cf" / "Configuration.xml").read_text(encoding="utf-8-sig")
    assert "<Report>Sales</Report>" not in cfg
    assert "<DataProcessor>ImportData</DataProcessor>" not in cfg


@pytest.mark.integration
def test_scheduled_job_event_subscription_get_update_delete_roundtrip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create → get full IR → update properties → delete (#65)."""
    from adapters.source.xmlgen import EditOp
    from adapters.source.xmlgen.resolve import resolve_jar as resolve_xmlgen
    from adapters.source.xmlgen.resolve import resolve_java as resolve_java_xml
    from core.metadata import (
        catalog_from_parts,
        create_metadata,
        delete_metadata,
        update_metadata,
    )

    local_jar = _local_md_reader_jar()
    if local_jar is not None:
        monkeypatch.setenv("ONEC_MDREADER_JAR", str(local_jar))

    java = resolve_java()
    jar = resolve_jar()
    if not java.found or not jar.found:
        pytest.skip(
            "md-reader jar / Java 21+ недоступны (запустите scripts/fetch-md-reader.sh)"
        )
    xmlgen = resolve_xmlgen()
    if not xmlgen.found or not resolve_java_xml().found:
        pytest.skip("xml-gen jar / Java 17+ недоступны (запустите scripts/fetch-xml-gen.sh)")

    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")

    assert create_metadata(
        target,
        catalog_from_parts(qualified_name="CommonModule.Jobs", server=True),
    ).status == "ok"
    assert create_metadata(
        target,
        catalog_from_parts(qualified_name="Catalog.Products"),
    ).status == "ok"

    created = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="ScheduledJob.Cleanup",
            synonym="Очистка",
            method_name="CommonModule.Jobs.Cleanup",
            use=True,
            description="Nightly",
            key="cleanup",
            predefined=False,
            restart_count_on_failure=5,
            restart_interval_on_failure=20,
        ),
    )
    assert created.status == "ok", created.diagnostics

    got = get_metadata(target, "ScheduledJob.Cleanup")
    assert got.status == "ok", got.diagnostics
    assert got.ir is not None
    assert got.ir["type"] == "ScheduledJob"
    assert got.ir["name"] == "Cleanup"
    assert got.ir["methodName"] == "CommonModule.Jobs.Cleanup"
    assert got.ir["use"] is True
    assert got.ir.get("description") == "Nightly"
    assert got.ir.get("key") == "cleanup"
    assert got.ir["predefined"] is False
    assert got.ir["restartCountOnFailure"] == 5
    assert got.ir["restartIntervalOnFailure"] == 20

    updated = update_metadata(
        target,
        "ScheduledJob.Cleanup",
        [
            EditOp("modify-property", "Use=false"),
            EditOp("modify-property", "Synonym=НочнаяОчистка"),
            EditOp("modify-property", "Description=Daily"),
        ],
    )
    assert updated.status == "ok", updated.diagnostics

    got2 = get_metadata(target, "ScheduledJob.Cleanup")
    assert got2.status == "ok", got2.diagnostics
    assert got2.ir is not None
    assert got2.ir["use"] is False
    assert got2.ir.get("synonym") == "НочнаяОчистка"
    assert got2.ir.get("description") == "Daily"

    sub = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="EventSubscription.ProductsBeforeWrite",
            synonym="ПередЗаписью",
            handler="CommonModule.Jobs.BeforeWrite",
            event="BeforeWrite",
            source=["Catalog.Products"],
        ),
    )
    assert sub.status == "ok", sub.diagnostics

    got_s = get_metadata(target, "EventSubscription.ProductsBeforeWrite")
    assert got_s.status == "ok", got_s.diagnostics
    assert got_s.ir is not None
    assert got_s.ir["type"] == "EventSubscription"
    assert got_s.ir["handler"] == "CommonModule.Jobs.BeforeWrite"
    assert got_s.ir["event"] == "BeforeWrite"
    assert got_s.ir["source"] == ["Catalog.Products"]

    updated_s = update_metadata(
        target,
        "EventSubscription.ProductsBeforeWrite",
        [
            EditOp("modify-property", "Event=OnWrite"),
            EditOp("modify-property", "Synonym=ПриЗаписи"),
        ],
    )
    assert updated_s.status == "ok", updated_s.diagnostics

    got_s2 = get_metadata(target, "EventSubscription.ProductsBeforeWrite")
    assert got_s2.status == "ok", got_s2.diagnostics
    assert got_s2.ir is not None
    assert got_s2.ir["event"] == "OnWrite"
    assert got_s2.ir.get("synonym") == "ПриЗаписи"

    deleted_j = delete_metadata(target, "ScheduledJob.Cleanup")
    assert deleted_j.status == "ok", deleted_j.diagnostics
    assert not (target / "src" / "cf" / "ScheduledJobs" / "Cleanup.xml").is_file()

    deleted_s = delete_metadata(target, "EventSubscription.ProductsBeforeWrite")
    assert deleted_s.status == "ok", deleted_s.diagnostics
    assert not (
        target / "src" / "cf" / "EventSubscriptions" / "ProductsBeforeWrite.xml"
    ).is_file()

    cfg = (target / "src" / "cf" / "Configuration.xml").read_text(encoding="utf-8-sig")
    assert "<ScheduledJob>Cleanup</ScheduledJob>" not in cfg
    assert "<EventSubscription>ProductsBeforeWrite</EventSubscription>" not in cfg


@pytest.mark.integration
def test_read_with_real_md_reader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    java = resolve_java()
    jar = resolve_jar()
    if not java.found or not jar.found:
        pytest.skip(
            "md-reader jar / Java 21+ недоступны (запустите scripts/fetch-md-reader.sh)"
        )

    target = tmp_path / "shop"
    target.mkdir()
    init = init_project(target, project_type="configuration", name="Shop")
    assert init.status == "ok"

    listed = list_metadata(target)
    assert listed.status == "ok", listed.diagnostics
    qnames = {o["qname"] for o in listed.objects}
    assert any(q.startswith("Language.") for q in qnames)

    # Optional: Catalog via xml-gen for full IR get
    from adapters.source.xmlgen.resolve import resolve_jar as resolve_xmlgen
    from adapters.source.xmlgen.resolve import resolve_java as resolve_java_xml
    from core.metadata import catalog_from_parts, create_metadata

    xmlgen = resolve_xmlgen()
    if xmlgen.found and resolve_java_xml().found:
        created = create_metadata(
            target,
            catalog_from_parts(
                qualified_name="Catalog.Products",
                synonym="Товары",
                attr_specs=["Article:String:50:Артикул"],
            ),
        )
        assert created.status == "ok", created.diagnostics
        got = get_metadata(target, "Catalog.Products")
        assert got.status == "ok", got.diagnostics
        assert got.ir is not None
        assert got.ir["type"] == "Catalog"
        assert got.ir["name"] == "Products"
        attrs = got.ir.get("attributes") or []
        names = {a.get("name") for a in attrs if isinstance(a, dict)}
        assert "Article" in names

        found = find_metadata(target, "Товар")
        assert found.status == "ok"
        assert any(o.get("qname") == "Catalog.Products" for o in found.objects)

    monkeypatch.chdir(target)
    cli = runner.invoke(app, ["metadata", "list", "--output", "json"])
    assert cli.exit_code == SUCCESS, cli.output
    payload = json.loads(cli.output)
    assert payload["status"] == "ok"
