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
    assert parse_qualified_name("Report.Sales") == ("Report", "Sales")
    assert parse_qualified_name("Subsystem.Main") == ("Subsystem", "Main")
    with pytest.raises(IrError) as exc:
        parse_qualified_name("Role.Admin")
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


def test_enum_from_parts_and_json() -> None:
    enum = catalog_from_parts(
        qualified_name="Enum.OrderStatuses",
        synonym="СтатусыЗаказа",
        value_specs=["New:Новый", "Done:Выполнен"],
    )
    assert enum.qualified_name == "Enum.OrderStatuses"
    assert len(enum.values) == 2
    assert enum.values[0].synonym == "Новый"
    dsl = ir_to_xmlgen_dsl(enum.to_dict())
    assert dsl["type"] == "Enum"
    assert dsl["values"] == [
        {"name": "New", "synonym": "Новый"},
        {"name": "Done", "synonym": "Выполнен"},
    ]
    assert "attributes" not in dsl

    from_json = catalog_from_json(
        {
            "type": "Enum",
            "name": "OrderStatuses",
            "values": [{"name": "New", "synonym": "Новый"}],
        }
    )
    assert from_json.values[0].name == "New"

    with pytest.raises(IrError) as exc:
        catalog_from_parts(
            qualified_name="Enum.Bad",
            attr_specs=["X:String:10"],
        )
    assert exc.value.code == "1CM004"


def test_register_from_parts_and_json() -> None:
    info = catalog_from_parts(
        qualified_name="InformationRegister.Prices",
        dimension_specs=["Product:Ref:Catalog.Products"],
        resource_specs=["Price:Number:15.2:Цена"],
    )
    assert info.type == "InformationRegister"
    dsl = ir_to_xmlgen_dsl(info.to_dict())
    assert dsl["dimensions"][0]["type"] == "CatalogRef.Products"
    assert dsl["resources"][0]["type"] == "Number(15,2)"
    assert dsl["resources"][0]["synonym"] == "Цена"

    accum = catalog_from_json(
        {
            "type": "AccumulationRegister",
            "name": "Stock",
            "dimensions": [
                {"name": "Product", "type": "Ref", "reference": "Catalog.Products"}
            ],
            "resources": [{"name": "Qty", "type": "Number", "precision": 15, "scale": 3}],
        }
    )
    assert accum.qualified_name == "AccumulationRegister.Stock"
    accum_dsl = ir_to_xmlgen_dsl(accum.to_dict())
    assert accum_dsl["resources"][0]["type"] == "Number(15,3)"

    with pytest.raises(IrError) as exc:
        catalog_from_parts(
            qualified_name="InformationRegister.Bad",
            value_specs=["X"],
        )
    assert exc.value.code == "1CM004"


def test_common_module_from_parts_and_json() -> None:
    mod = catalog_from_parts(
        qualified_name="CommonModule.SalesServer",
        synonym="ПродажиСервер",
        server=True,
        server_call=True,
    )
    assert mod.qualified_name == "CommonModule.SalesServer"
    assert mod.server is True
    assert mod.server_call is True
    dsl = ir_to_xmlgen_dsl(mod.to_dict())
    assert dsl == {
        "type": "CommonModule",
        "name": "SalesServer",
        "synonym": "ПродажиСервер",
        "server": True,
        "serverCall": True,
    }
    assert "attributes" not in dsl

    from_json = catalog_from_json(
        {
            "type": "CommonModule",
            "name": "Utils",
            "client": True,
            "privileged": True,
            "returnValuesReuse": "DuringRequest",
        }
    )
    assert from_json.client_managed_application is True
    assert from_json.privileged is True
    assert from_json.return_values_reuse == "DuringRequest"
    sugar_dsl = ir_to_xmlgen_dsl(from_json.to_dict())
    assert sugar_dsl["clientManagedApplication"] is True
    assert sugar_dsl["returnValuesReuse"] == "DuringRequest"
    assert "client" not in sugar_dsl

    with pytest.raises(IrError) as conflict:
        catalog_from_json(
            {
                "type": "CommonModule",
                "name": "Bad",
                "client": True,
                "clientManagedApplication": False,
            }
        )
    assert conflict.value.code == "1CM004"

    with pytest.raises(IrError) as shape:
        catalog_from_parts(
            qualified_name="CommonModule.Bad",
            attr_specs=["X:String:10"],
        )
    assert shape.value.code == "1CM004"


def test_subsystem_from_parts_and_json() -> None:
    from adapters.source.xmlgen.subsystem import ir_to_subsystem_dsl

    sub = catalog_from_parts(
        qualified_name="Subsystem.Main",
        synonym="Главная",
        content=["Catalog.Products"],
        children=["Sales"],
        include_in_command_interface=True,
    )
    assert sub.qualified_name == "Subsystem.Main"
    assert sub.content == ["Catalog.Products"]
    assert sub.children == ["Sales"]
    assert sub.include_in_command_interface is True
    ir = sub.to_dict()
    assert ir == {
        "type": "Subsystem",
        "name": "Main",
        "synonym": "Главная",
        "content": ["Catalog.Products"],
        "children": ["Sales"],
        "includeInCommandInterface": True,
    }
    dsl = ir_to_subsystem_dsl(ir)
    assert dsl["name"] == "Main"
    assert dsl["content"] == ["Catalog.Products"]
    assert dsl["children"] == ["Sales"]
    assert "type" not in dsl

    from_json = catalog_from_json(
        {
            "type": "Subsystem",
            "name": "Reports",
            "content": ["Report.Sales"],
            "includeInCommandInterface": False,
        }
    )
    assert from_json.content == ["Report.Sales"]
    assert from_json.include_in_command_interface is False

    with pytest.raises(IrError) as shape:
        catalog_from_parts(
            qualified_name="Subsystem.Bad",
            attr_specs=["X:String:10"],
        )
    assert shape.value.code == "1CM004"

    with pytest.raises(IrError) as bad_content:
        catalog_from_parts(
            qualified_name="Subsystem.Bad",
            content=["Products"],
        )
    assert bad_content.value.code == "1CM004"


def test_constant_and_defined_type_from_parts_and_json() -> None:
    const = catalog_from_parts(
        qualified_name="Constant.VATRate",
        synonym="СтавкаНДС",
        value_type_specs=["Number:5.2"],
    )
    assert const.qualified_name == "Constant.VATRate"
    assert const.value_type is not None
    assert const.value_type.type == "Number"
    assert const.value_type.precision == 5
    assert const.value_type.scale == 2
    dsl = ir_to_xmlgen_dsl(const.to_dict())
    assert dsl == {
        "type": "Constant",
        "name": "VATRate",
        "synonym": "СтавкаНДС",
        "valueType": "Number(5,2)",
    }
    assert "attributes" not in dsl

    defined = catalog_from_parts(
        qualified_name="DefinedType.CounterpartyRef",
        value_type_specs=["String:50", "Number:10.0"],
    )
    assert defined.value_types[0].type == "String"
    assert defined.value_types[0].length == 50
    defined_dsl = ir_to_xmlgen_dsl(defined.to_dict())
    assert defined_dsl["type"] == "DefinedType"
    assert defined_dsl["valueTypes"] == ["String(50)", "Number(10,0)"]

    from_json = catalog_from_json(
        {
            "type": "DefinedType",
            "name": "Money",
            "valueType": {"type": "Number", "precision": 15, "scale": 2},
        }
    )
    assert len(from_json.value_types) == 1
    assert from_json.value_types[0].precision == 15

    with pytest.raises(IrError) as shape:
        catalog_from_parts(
            qualified_name="Constant.Bad",
            attr_specs=["X:String:10"],
        )
    assert shape.value.code == "1CM004"

    with pytest.raises(IrError) as required:
        catalog_from_parts(qualified_name="DefinedType.Bad")
    assert required.value.code == "1CM004"


def test_report_and_dataprocessor_from_parts_and_json() -> None:
    report = catalog_from_parts(
        qualified_name="Report.Sales",
        synonym="Продажи",
        attr_specs=["Period:Date:Период"],
        ts_specs=["Lines:Строки"],
        ts_attr_specs=["Lines.Amount:Number:15.2:Сумма"],
    )
    assert report.qualified_name == "Report.Sales"
    assert report.type == "Report"
    assert len(report.attributes) == 1
    assert report.attributes[0].name == "Period"
    assert len(report.tabular_sections) == 1
    assert report.tabular_sections[0].name == "Lines"
    dsl = ir_to_xmlgen_dsl(report.to_dict())
    assert dsl["type"] == "Report"
    assert dsl["attributes"][0]["type"] == "Date"
    assert "Lines" in dsl["tabularSections"]

    processor = catalog_from_parts(
        qualified_name="DataProcessor.ImportData",
        synonym="Загрузка",
        attr_specs=["Path:String:200:Путь"],
    )
    assert processor.qualified_name == "DataProcessor.ImportData"
    proc_dsl = ir_to_xmlgen_dsl(processor.to_dict())
    assert proc_dsl["type"] == "DataProcessor"
    assert proc_dsl["attributes"][0]["type"] == "String(200)"

    from_json = catalog_from_json(
        {
            "type": "Report",
            "name": "Margin",
            "attributes": [{"name": "Cutoff", "type": "Number", "precision": 10, "scale": 2}],
            "tabularSections": [
                {
                    "name": "Rows",
                    "attributes": [{"name": "Qty", "type": "Number", "precision": 15, "scale": 3}],
                }
            ],
        }
    )
    assert from_json.type == "Report"
    assert from_json.attributes[0].name == "Cutoff"
    assert from_json.tabular_sections[0].name == "Rows"

    with pytest.raises(IrError) as shape:
        catalog_from_parts(
            qualified_name="Report.Bad",
            value_type_specs=["String:10"],
        )
    assert shape.value.code == "1CM004"


def test_scheduled_job_and_event_subscription_from_parts_and_json() -> None:
    job = catalog_from_parts(
        qualified_name="ScheduledJob.Cleanup",
        synonym="Очистка",
        method_name="CommonModule.Jobs.Cleanup",
        use=True,
        description="Nightly",
        key="cleanup",
        predefined=False,
        restart_count_on_failure=5,
        restart_interval_on_failure=20,
    )
    assert job.qualified_name == "ScheduledJob.Cleanup"
    assert job.type == "ScheduledJob"
    assert job.method_name == "CommonModule.Jobs.Cleanup"
    assert job.use is True
    dsl = ir_to_xmlgen_dsl(job.to_dict())
    assert dsl == {
        "type": "ScheduledJob",
        "name": "Cleanup",
        "synonym": "Очистка",
        "methodName": "CommonModule.Jobs.Cleanup",
        "use": True,
        "description": "Nightly",
        "key": "cleanup",
        "predefined": False,
        "restartCountOnFailure": 5,
        "restartIntervalOnFailure": 20,
    }
    assert "attributes" not in dsl

    sub = catalog_from_parts(
        qualified_name="EventSubscription.ProductsBeforeWrite",
        synonym="ПередЗаписью",
        handler="CommonModule.Jobs.BeforeWrite",
        event="BeforeWrite",
        source=["Catalog.Products"],
    )
    assert sub.qualified_name == "EventSubscription.ProductsBeforeWrite"
    assert sub.handler == "CommonModule.Jobs.BeforeWrite"
    assert sub.event == "BeforeWrite"
    assert sub.source == ["Catalog.Products"]
    sub_dsl = ir_to_xmlgen_dsl(sub.to_dict())
    assert sub_dsl["type"] == "EventSubscription"
    assert sub_dsl["handler"] == "CommonModule.Jobs.BeforeWrite"
    assert sub_dsl["event"] == "BeforeWrite"
    assert sub_dsl["source"] == ["Catalog.Products"]

    from_json = catalog_from_json(
        {
            "type": "ScheduledJob",
            "name": "Rebuild",
            "methodName": "CommonModule.Jobs.Rebuild",
            "use": False,
        }
    )
    assert from_json.type == "ScheduledJob"
    assert from_json.method_name == "CommonModule.Jobs.Rebuild"
    assert from_json.use is False

    from_json_es = catalog_from_json(
        {
            "type": "EventSubscription",
            "name": "DocOnWrite",
            "handler": "CommonModule.Jobs.OnWrite",
            "event": "OnWrite",
            "source": ["Document.Order"],
        }
    )
    assert from_json_es.source == ["Document.Order"]

    with pytest.raises(IrError) as shape:
        catalog_from_parts(
            qualified_name="ScheduledJob.Bad",
            attr_specs=["X:String:10"],
        )
    assert shape.value.code == "1CM004"

    with pytest.raises(IrError) as bad_handler:
        catalog_from_parts(
            qualified_name="EventSubscription.Bad",
            handler="Jobs.BeforeWrite",
        )
    assert bad_handler.value.code == "1CM004"

    with pytest.raises(IrError) as bad_source:
        catalog_from_parts(
            qualified_name="EventSubscription.Bad",
            source=["Products"],
        )
    assert bad_source.value.code == "1CM004"


def test_http_service_and_web_service_from_parts_and_json() -> None:
    http = catalog_from_parts(
        qualified_name="HTTPService.API",
        synonym="API",
        root_url="api",
        reuse_sessions="DontUse",
        session_max_age=20,
        url_templates={
            "Users": {
                "template": "/v1/users",
                "methods": {"Get": "GET", "Create": "POST"},
            }
        },
    )
    assert http.qualified_name == "HTTPService.API"
    assert http.type == "HTTPService"
    assert http.root_url == "api"
    assert http.reuse_sessions == "DontUse"
    assert http.session_max_age == 20
    assert http.url_templates["Users"]["template"] == "/v1/users"
    assert http.url_templates["Users"]["methods"]["Get"] == "GET"
    dsl = ir_to_xmlgen_dsl(http.to_dict())
    assert dsl == {
        "type": "HTTPService",
        "name": "API",
        "synonym": "API",
        "rootURL": "api",
        "reuseSessions": "DontUse",
        "sessionMaxAge": 20,
        "urlTemplates": {
            "Users": {
                "template": "/v1/users",
                "methods": {"Get": "GET", "Create": "POST"},
            }
        },
    }
    assert "attributes" not in dsl

    web = catalog_from_parts(
        qualified_name="WebService.DataExchange",
        synonym="Обмен",
        namespace="http://www.1c.ru/DataExchange",
        reuse_sessions="DontUse",
        session_max_age=20,
        operations={
            "TestConnection": {
                "returnType": "xs:boolean",
                "handler": "ПроверкаПодключения",
                "parameters": {
                    "ErrorMessage": {"type": "xs:string", "direction": "Out"}
                },
            }
        },
    )
    assert web.qualified_name == "WebService.DataExchange"
    assert web.namespace == "http://www.1c.ru/DataExchange"
    assert web.operations["TestConnection"]["handler"] == "ПроверкаПодключения"
    web_dsl = ir_to_xmlgen_dsl(web.to_dict())
    assert web_dsl["type"] == "WebService"
    assert web_dsl["namespace"] == "http://www.1c.ru/DataExchange"
    assert web_dsl["operations"]["TestConnection"]["returnType"] == "xs:boolean"
    assert web_dsl["operations"]["TestConnection"]["parameters"]["ErrorMessage"][
        "direction"
    ] == "Out"

    from_json = catalog_from_json(
        {
            "type": "HTTPService",
            "name": "Public",
            "rootURL": "public",
            "urlTemplates": {"Ping": "/ping"},
        }
    )
    assert from_json.type == "HTTPService"
    assert from_json.root_url == "public"
    assert from_json.url_templates["Ping"]["template"] == "/ping"

    from_json_ws = catalog_from_json(
        {
            "type": "WebService",
            "name": "Exchange",
            "namespace": "http://example.com",
            "operations": {
                "Echo": {"handler": "EchoHandler", "returnType": "xs:string"}
            },
        }
    )
    assert from_json_ws.operations["Echo"]["handler"] == "EchoHandler"

    with pytest.raises(IrError) as shape:
        catalog_from_parts(
            qualified_name="HTTPService.Bad",
            attr_specs=["X:String:10"],
        )
    assert shape.value.code == "1CM004"

    with pytest.raises(IrError) as bad_verb:
        catalog_from_parts(
            qualified_name="HTTPService.Bad",
            url_templates={"T": {"template": "/t", "methods": {"X": "FOO"}}},
        )
    assert bad_verb.value.code == "1CM004"

    with pytest.raises(IrError) as cross:
        catalog_from_parts(
            qualified_name="WebService.Bad",
            root_url="api",
        )
    assert cross.value.code == "1CM004"


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


def test_create_enum_mock(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(target, project_type="configuration", name="Shop").status == "ok"

    def fake_compile(source_dir: Path, dsl: dict[str, Any]) -> list[str]:
        assert dsl["type"] == "Enum"
        assert dsl["values"][0]["name"] == "New"
        enums = source_dir / "Enums"
        enums.mkdir(parents=True)
        (enums / "OrderStatuses.xml").write_text("<Enum/>", encoding="utf-8")
        cfg = source_dir / "Configuration.xml"
        text = cfg.read_text(encoding="utf-8-sig")
        text = text.replace(
            "<Language>Русский</Language>",
            "<Language>Русский</Language>\r\n\t\t\t<Enum>OrderStatuses</Enum>",
        )
        cfg.write_text(text, encoding="utf-8-sig", newline="")
        return ["Enums/OrderStatuses.xml", "Configuration.xml"]

    enum = catalog_from_parts(
        qualified_name="Enum.OrderStatuses",
        synonym="Статусы",
        value_specs=["New:Новый", "Done:Выполнен"],
    )
    result = create_metadata(target, enum, compile_fn=fake_compile)
    assert result.status == "ok"
    assert result.object == "Enum.OrderStatuses"
    assert any("Enums/OrderStatuses.xml" in p for p in result.created)


def test_create_registers_mock(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(target, project_type="configuration", name="Shop").status == "ok"

    seen: list[str] = []

    def fake_compile(source_dir: Path, dsl: dict[str, Any]) -> list[str]:
        seen.append(dsl["type"])
        folder = {
            "InformationRegister": "InformationRegisters",
            "AccumulationRegister": "AccumulationRegisters",
        }[dsl["type"]]
        name = dsl["name"]
        path = source_dir / folder
        path.mkdir(parents=True)
        (path / f"{name}.xml").write_text(f"<{dsl['type']}/>", encoding="utf-8")
        assert dsl["dimensions"][0]["name"] == "Product"
        assert dsl["resources"][0]["name"] in ("Price", "Qty")
        cfg = source_dir / "Configuration.xml"
        text = cfg.read_text(encoding="utf-8-sig")
        tag = dsl["type"]
        text = text.replace(
            "<Language>Русский</Language>",
            f"<Language>Русский</Language>\r\n\t\t\t<{tag}>{name}</{tag}>",
        )
        cfg.write_text(text, encoding="utf-8-sig", newline="")
        return [f"{folder}/{name}.xml", "Configuration.xml"]

    info = catalog_from_parts(
        qualified_name="InformationRegister.Prices",
        dimension_specs=["Product:Ref:Catalog.Products"],
        resource_specs=["Price:Number:15.2:Цена"],
    )
    r1 = create_metadata(target, info, compile_fn=fake_compile)
    assert r1.status == "ok", r1.diagnostics

    accum = catalog_from_parts(
        qualified_name="AccumulationRegister.Stock",
        dimension_specs=["Product:Ref:Catalog.Products"],
        resource_specs=["Qty:Number:15.3"],
    )
    r2 = create_metadata(target, accum, compile_fn=fake_compile)
    assert r2.status == "ok", r2.diagnostics
    assert seen == ["InformationRegister", "AccumulationRegister"]


def test_create_common_module_mock(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(target, project_type="configuration", name="Shop").status == "ok"

    def fake_compile(source_dir: Path, dsl: dict[str, Any]) -> list[str]:
        assert dsl["type"] == "CommonModule"
        assert dsl["name"] == "SalesServer"
        assert dsl["server"] is True
        assert dsl.get("clientManagedApplication") is None
        mods = source_dir / "CommonModules"
        mods.mkdir(parents=True)
        (mods / "SalesServer.xml").write_text("<CommonModule/>", encoding="utf-8")
        bsl = mods / "SalesServer" / "Ext"
        bsl.mkdir(parents=True)
        (bsl / "Module.bsl").write_bytes(b"\xef\xbb\xbf")
        cfg = source_dir / "Configuration.xml"
        text = cfg.read_text(encoding="utf-8-sig")
        text = text.replace(
            "<Language>Русский</Language>",
            "<Language>Русский</Language>\r\n\t\t\t"
            "<CommonModule>SalesServer</CommonModule>",
        )
        cfg.write_text(text, encoding="utf-8-sig", newline="")
        return [
            "CommonModules/SalesServer.xml",
            "CommonModules/SalesServer/Ext/Module.bsl",
            "Configuration.xml",
        ]

    mod = catalog_from_parts(
        qualified_name="CommonModule.SalesServer",
        synonym="ПродажиСервер",
        server=True,
    )
    result = create_metadata(target, mod, compile_fn=fake_compile)
    assert result.status == "ok", result.diagnostics
    assert result.object == "CommonModule.SalesServer"
    assert any("CommonModules/SalesServer.xml" in p for p in result.created)


def test_create_subsystem_mock(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(target, project_type="configuration", name="Shop").status == "ok"

    def fake_compile(source_dir: Path, dsl: dict[str, Any]) -> list[str]:
        assert "type" not in dsl
        assert dsl["name"] == "Main"
        assert dsl["synonym"] == "Главная"
        assert dsl["includeInCommandInterface"] is True
        assert dsl.get("content") == []
        subs = source_dir / "Subsystems"
        subs.mkdir(parents=True)
        (subs / "Main.xml").write_text("<Subsystem/>", encoding="utf-8")
        cfg = source_dir / "Configuration.xml"
        text = cfg.read_text(encoding="utf-8-sig")
        text = text.replace(
            "<Language>Русский</Language>",
            "<Language>Русский</Language>\r\n\t\t\t"
            "<Subsystem>Main</Subsystem>",
        )
        cfg.write_text(text, encoding="utf-8-sig", newline="")
        return ["Subsystems/Main.xml", "Configuration.xml"]

    sub = catalog_from_parts(
        qualified_name="Subsystem.Main",
        synonym="Главная",
        include_in_command_interface=True,
    )
    result = create_metadata(target, sub, compile_fn=fake_compile)
    assert result.status == "ok", result.diagnostics
    assert result.object == "Subsystem.Main"
    assert any("Subsystems/Main.xml" in p for p in result.created)


def test_create_constant_and_defined_type_mock(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(target, project_type="configuration", name="Shop").status == "ok"

    def fake_compile_const(source_dir: Path, dsl: dict[str, Any]) -> list[str]:
        assert dsl["type"] == "Constant"
        assert dsl["valueType"] == "Number(5,2)"
        folder = source_dir / "Constants"
        folder.mkdir(parents=True)
        (folder / "VATRate.xml").write_text("<Constant/>", encoding="utf-8")
        return ["Constants/VATRate.xml"]

    result = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="Constant.VATRate",
            synonym="СтавкаНДС",
            value_type_specs=["Number:5.2"],
        ),
        compile_fn=fake_compile_const,
    )
    assert result.status == "ok"
    assert result.object == "Constant.VATRate"

    def fake_compile_defined(source_dir: Path, dsl: dict[str, Any]) -> list[str]:
        assert dsl["type"] == "DefinedType"
        assert dsl["valueTypes"] == ["String(50)"]
        folder = source_dir / "DefinedTypes"
        folder.mkdir(parents=True)
        (folder / "MoneyCode.xml").write_text("<DefinedType/>", encoding="utf-8")
        return ["DefinedTypes/MoneyCode.xml"]

    result2 = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="DefinedType.MoneyCode",
            value_type_specs=["String:50"],
        ),
        compile_fn=fake_compile_defined,
    )
    assert result2.status == "ok"
    assert result2.object == "DefinedType.MoneyCode"


def test_create_report_and_dataprocessor_mock(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(target, project_type="configuration", name="Shop").status == "ok"

    def fake_compile_report(source_dir: Path, dsl: dict[str, Any]) -> list[str]:
        assert dsl["type"] == "Report"
        assert dsl["name"] == "Sales"
        assert len(dsl["attributes"]) == 1
        assert "Lines" in dsl["tabularSections"]
        folder = source_dir / "Reports"
        folder.mkdir(parents=True)
        (folder / "Sales.xml").write_text("<Report/>", encoding="utf-8")
        return ["Reports/Sales.xml"]

    result = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="Report.Sales",
            synonym="Продажи",
            attr_specs=["Period:Date"],
            ts_specs=["Lines"],
            ts_attr_specs=["Lines.Amount:Number:15.2"],
        ),
        compile_fn=fake_compile_report,
    )
    assert result.status == "ok"
    assert result.object == "Report.Sales"

    def fake_compile_processor(source_dir: Path, dsl: dict[str, Any]) -> list[str]:
        assert dsl["type"] == "DataProcessor"
        assert dsl["attributes"][0]["type"] == "String(200)"
        folder = source_dir / "DataProcessors"
        folder.mkdir(parents=True)
        (folder / "ImportData.xml").write_text("<DataProcessor/>", encoding="utf-8")
        return ["DataProcessors/ImportData.xml"]

    result2 = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="DataProcessor.ImportData",
            attr_specs=["Path:String:200"],
        ),
        compile_fn=fake_compile_processor,
    )
    assert result2.status == "ok"
    assert result2.object == "DataProcessor.ImportData"


def test_create_scheduled_job_and_event_subscription_mock(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(target, project_type="configuration", name="Shop").status == "ok"

    def fake_compile_job(source_dir: Path, dsl: dict[str, Any]) -> list[str]:
        assert dsl["type"] == "ScheduledJob"
        assert dsl["methodName"] == "CommonModule.Jobs.Cleanup"
        assert dsl["use"] is True
        folder = source_dir / "ScheduledJobs"
        folder.mkdir(parents=True)
        (folder / "Cleanup.xml").write_text("<ScheduledJob/>", encoding="utf-8")
        return ["ScheduledJobs/Cleanup.xml"]

    result = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="ScheduledJob.Cleanup",
            synonym="Очистка",
            method_name="CommonModule.Jobs.Cleanup",
            use=True,
        ),
        compile_fn=fake_compile_job,
    )
    assert result.status == "ok"
    assert result.object == "ScheduledJob.Cleanup"

    def fake_compile_sub(source_dir: Path, dsl: dict[str, Any]) -> list[str]:
        assert dsl["type"] == "EventSubscription"
        assert dsl["handler"] == "CommonModule.Jobs.BeforeWrite"
        assert dsl["event"] == "BeforeWrite"
        assert dsl["source"] == ["Catalog.Products"]
        folder = source_dir / "EventSubscriptions"
        folder.mkdir(parents=True)
        (folder / "ProductsBeforeWrite.xml").write_text(
            "<EventSubscription/>", encoding="utf-8"
        )
        return ["EventSubscriptions/ProductsBeforeWrite.xml"]

    result2 = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="EventSubscription.ProductsBeforeWrite",
            handler="CommonModule.Jobs.BeforeWrite",
            event="BeforeWrite",
            source=["Catalog.Products"],
        ),
        compile_fn=fake_compile_sub,
    )
    assert result2.status == "ok"
    assert result2.object == "EventSubscription.ProductsBeforeWrite"


def test_create_http_service_and_web_service_mock(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(target, project_type="configuration", name="Shop").status == "ok"

    def fake_compile_http(source_dir: Path, dsl: dict[str, Any]) -> list[str]:
        assert dsl["type"] == "HTTPService"
        assert dsl["rootURL"] == "api"
        assert dsl["urlTemplates"]["Users"]["methods"]["Get"] == "GET"
        folder = source_dir / "HTTPServices"
        folder.mkdir(parents=True)
        (folder / "API.xml").write_text("<HTTPService/>", encoding="utf-8")
        return ["HTTPServices/API.xml"]

    result = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="HTTPService.API",
            synonym="API",
            root_url="api",
            url_templates={
                "Users": {
                    "template": "/v1/users",
                    "methods": {"Get": "GET", "Create": "POST"},
                }
            },
        ),
        compile_fn=fake_compile_http,
    )
    assert result.status == "ok"
    assert result.object == "HTTPService.API"

    def fake_compile_web(source_dir: Path, dsl: dict[str, Any]) -> list[str]:
        assert dsl["type"] == "WebService"
        assert dsl["namespace"] == "http://www.1c.ru/DataExchange"
        assert dsl["operations"]["TestConnection"]["handler"] == "ПроверкаПодключения"
        folder = source_dir / "WebServices"
        folder.mkdir(parents=True)
        (folder / "DataExchange.xml").write_text("<WebService/>", encoding="utf-8")
        return ["WebServices/DataExchange.xml"]

    result2 = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="WebService.DataExchange",
            namespace="http://www.1c.ru/DataExchange",
            operations={
                "TestConnection": {
                    "returnType": "xs:boolean",
                    "handler": "ПроверкаПодключения",
                    "parameters": {
                        "ErrorMessage": {"type": "xs:string", "direction": "Out"}
                    },
                }
            },
        ),
        compile_fn=fake_compile_web,
    )
    assert result2.status == "ok"
    assert result2.object == "WebService.DataExchange"


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


def test_cli_create_enum_and_register_mock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")

    def fake_compile(source_dir: Path, dsl: dict[str, Any]) -> list[str]:
        if dsl["type"] == "Enum":
            folder = source_dir / "Enums"
            folder.mkdir(parents=True)
            (folder / f"{dsl['name']}.xml").write_text("<Enum/>", encoding="utf-8")
            return [f"Enums/{dsl['name']}.xml"]
        folder = source_dir / "InformationRegisters"
        folder.mkdir(parents=True)
        (folder / f"{dsl['name']}.xml").write_text("<IR/>", encoding="utf-8")
        assert dsl["dimensions"][0]["type"] == "CatalogRef.Products"
        return [f"InformationRegisters/{dsl['name']}.xml"]

    from adapters.source.xmlgen.resolve import ToolResolve

    monkeypatch.setattr("core.metadata.create.compile_metadata", fake_compile)
    monkeypatch.setattr(
        "core.metadata.create.resolve_java",
        lambda: ToolResolve(found=True, path=Path("/usr/bin/java"), version="21"),
    )
    monkeypatch.setattr(
        "core.metadata.create.resolve_jar",
        lambda: ToolResolve(found=True, path=tmp_path / "xml-gen.jar"),
    )
    monkeypatch.chdir(target)

    enum_result = runner.invoke(
        app,
        [
            "metadata",
            "create",
            "Enum.OrderStatuses",
            "--synonym",
            "Статусы",
            "--value",
            "New:Новый",
            "--value",
            "Done:Выполнен",
            "--output",
            "json",
        ],
    )
    assert enum_result.exit_code == SUCCESS, enum_result.output
    assert json.loads(enum_result.output)["object"] == "Enum.OrderStatuses"

    reg_result = runner.invoke(
        app,
        [
            "metadata",
            "create",
            "InformationRegister.Prices",
            "--dimension",
            "Product:Ref:Catalog.Products",
            "--resource",
            "Price:Number:15.2:Цена",
            "--output",
            "json",
        ],
    )
    assert reg_result.exit_code == SUCCESS, reg_result.output
    assert json.loads(reg_result.output)["object"] == "InformationRegister.Prices"


def test_cli_create_common_module_mock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")

    def fake_compile(source_dir: Path, dsl: dict[str, Any]) -> list[str]:
        assert dsl["type"] == "CommonModule"
        assert dsl["server"] is True
        assert dsl["serverCall"] is True
        assert dsl["clientManagedApplication"] is True
        folder = source_dir / "CommonModules"
        folder.mkdir(parents=True)
        (folder / f"{dsl['name']}.xml").write_text("<CommonModule/>", encoding="utf-8")
        return [f"CommonModules/{dsl['name']}.xml"]

    from adapters.source.xmlgen.resolve import ToolResolve

    monkeypatch.setattr("core.metadata.create.compile_metadata", fake_compile)
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
            "CommonModule.SalesClientServer",
            "--synonym",
            "ПродажиКлиентСервер",
            "--server",
            "--client",
            "--server-call",
            "--output",
            "json",
        ],
    )
    assert result.exit_code == SUCCESS, result.output
    assert json.loads(result.output)["object"] == "CommonModule.SalesClientServer"


def test_cli_bad_type(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")
    monkeypatch.chdir(target)
    result = runner.invoke(
        app,
        ["metadata", "create", "Role.Admin", "--output", "json"],
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


@pytest.mark.integration
def test_create_enum_and_registers_with_real_xmlgen(tmp_path: Path) -> None:
    jar = resolve_jar()
    java = resolve_java()
    if not jar.found or not java.found:
        pytest.skip("xml-gen jar / Java 17+ недоступны (запустите scripts/fetch-xml-gen.sh)")

    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")

    cat = create_metadata(
        target,
        catalog_from_parts(qualified_name="Catalog.Products", synonym="Товары"),
    )
    assert cat.status == "ok", cat.diagnostics

    enum = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="Enum.OrderStatuses",
            synonym="СтатусыЗаказа",
            value_specs=["New:Новый", "Done:Выполнен"],
        ),
    )
    assert enum.status == "ok", enum.diagnostics
    enum_xml = target / "src" / "cf" / "Enums" / "OrderStatuses.xml"
    assert enum_xml.is_file()
    enum_text = enum_xml.read_text(encoding="utf-8-sig")
    assert "New" in enum_text
    assert "Done" in enum_text

    info = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="InformationRegister.Prices",
            dimension_specs=["Product:Ref:Catalog.Products"],
            resource_specs=["Price:Number:15.2:Цена"],
        ),
    )
    assert info.status == "ok", info.diagnostics
    prices = target / "src" / "cf" / "InformationRegisters" / "Prices.xml"
    assert prices.is_file()
    prices_text = prices.read_text(encoding="utf-8-sig")
    assert "Product" in prices_text
    assert "Price" in prices_text

    accum = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="AccumulationRegister.Stock",
            dimension_specs=["Product:Ref:Catalog.Products"],
            resource_specs=["Qty:Number:15.3"],
        ),
    )
    assert accum.status == "ok", accum.diagnostics
    stock = target / "src" / "cf" / "AccumulationRegisters" / "Stock.xml"
    assert stock.is_file()

    cfg = (target / "src" / "cf" / "Configuration.xml").read_text(encoding="utf-8-sig")
    assert "<Enum>OrderStatuses</Enum>" in cfg
    assert "<InformationRegister>Prices</InformationRegister>" in cfg
    assert "<AccumulationRegister>Stock</AccumulationRegister>" in cfg

    from core.project import validate_project

    assert validate_project(target).status == "ok"


@pytest.mark.integration
def test_create_common_module_with_real_xmlgen(tmp_path: Path) -> None:
    jar = resolve_jar()
    java = resolve_java()
    if not jar.found or not java.found:
        pytest.skip("xml-gen jar / Java 17+ недоступны (запустите scripts/fetch-xml-gen.sh)")

    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")

    mod = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="CommonModule.SalesServer",
            synonym="ПродажиСервер",
            server=True,
            server_call=True,
        ),
    )
    assert mod.status == "ok", mod.diagnostics
    xml_path = target / "src" / "cf" / "CommonModules" / "SalesServer.xml"
    assert xml_path.is_file()
    text = xml_path.read_text(encoding="utf-8-sig")
    assert "<Server>true</Server>" in text
    assert "<ServerCall>true</ServerCall>" in text
    bsl = target / "src" / "cf" / "CommonModules" / "SalesServer" / "Ext" / "Module.bsl"
    assert bsl.is_file()
    cfg = (target / "src" / "cf" / "Configuration.xml").read_text(encoding="utf-8-sig")
    assert "<CommonModule>SalesServer</CommonModule>" in cfg

    from core.project import validate_project

    assert validate_project(target).status == "ok"


@pytest.mark.integration
def test_create_subsystem_with_real_xmlgen(tmp_path: Path) -> None:
    jar = resolve_jar()
    java = resolve_java()
    if not jar.found or not java.found:
        pytest.skip("xml-gen jar / Java 17+ недоступны (запустите scripts/fetch-xml-gen.sh)")

    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")

    # Content refs must exist before subsystem compile (xml-gen fail-fast).
    cat = create_metadata(
        target,
        catalog_from_parts(qualified_name="Catalog.Products", synonym="Товары"),
    )
    assert cat.status == "ok", cat.diagnostics

    sub = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="Subsystem.Main",
            synonym="Главная",
            content=["Catalog.Products"],
            children=["Sales"],
            include_in_command_interface=True,
        ),
    )
    assert sub.status == "ok", sub.diagnostics
    xml_path = target / "src" / "cf" / "Subsystems" / "Main.xml"
    assert xml_path.is_file()
    text = xml_path.read_text(encoding="utf-8-sig")
    assert "Catalog.Products" in text
    assert "<Subsystem>Sales</Subsystem>" in text
    assert "<IncludeInCommandInterface>true</IncludeInCommandInterface>" in text
    cfg = (target / "src" / "cf" / "Configuration.xml").read_text(encoding="utf-8-sig")
    assert "<Subsystem>Main</Subsystem>" in cfg

    from core.project import validate_project

    assert validate_project(target).status == "ok"


@pytest.mark.integration
def test_create_constant_and_defined_type_with_real_xmlgen(tmp_path: Path) -> None:
    jar = resolve_jar()
    java = resolve_java()
    if not jar.found or not java.found:
        pytest.skip("xml-gen jar / Java 17+ недоступны (запустите scripts/fetch-xml-gen.sh)")

    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")

    const = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="Constant.VATRate",
            synonym="СтавкаНДС",
            value_type_specs=["Number:5.2"],
        ),
    )
    assert const.status == "ok", const.diagnostics
    const_xml = target / "src" / "cf" / "Constants" / "VATRate.xml"
    assert const_xml.is_file()
    const_text = const_xml.read_text(encoding="utf-8-sig")
    assert "xs:decimal" in const_text
    assert "<v8:Digits>5</v8:Digits>" in const_text

    defined = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="DefinedType.MoneyCode",
            value_type_specs=["String:50"],
        ),
    )
    assert defined.status == "ok", defined.diagnostics
    defined_xml = target / "src" / "cf" / "DefinedTypes" / "MoneyCode.xml"
    assert defined_xml.is_file()
    defined_text = defined_xml.read_text(encoding="utf-8-sig")
    assert "xs:string" in defined_text
    assert "<v8:Length>50</v8:Length>" in defined_text

    cfg = (target / "src" / "cf" / "Configuration.xml").read_text(encoding="utf-8-sig")
    assert "<Constant>VATRate</Constant>" in cfg
    assert "<DefinedType>MoneyCode</DefinedType>" in cfg

    from core.project import validate_project

    assert validate_project(target).status == "ok"


@pytest.mark.integration
def test_create_report_and_dataprocessor_with_real_xmlgen(tmp_path: Path) -> None:
    jar = resolve_jar()
    java = resolve_java()
    if not jar.found or not java.found:
        pytest.skip("xml-gen jar / Java 17+ недоступны (запустите scripts/fetch-xml-gen.sh)")

    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")

    report = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="Report.Sales",
            synonym="Продажи",
            attr_specs=["Period:Date:Период"],
            ts_specs=["Lines:Строки"],
            ts_attr_specs=["Lines.Amount:Number:15.2:Сумма"],
        ),
    )
    assert report.status == "ok", report.diagnostics
    report_xml = target / "src" / "cf" / "Reports" / "Sales.xml"
    assert report_xml.is_file()
    report_text = report_xml.read_text(encoding="utf-8-sig")
    assert "<Name>Period</Name>" in report_text
    assert "<Name>Lines</Name>" in report_text
    assert "<Name>Amount</Name>" in report_text

    processor = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="DataProcessor.ImportData",
            synonym="Загрузка",
            attr_specs=["Path:String:200:Путь"],
        ),
    )
    assert processor.status == "ok", processor.diagnostics
    proc_xml = target / "src" / "cf" / "DataProcessors" / "ImportData.xml"
    assert proc_xml.is_file()
    proc_text = proc_xml.read_text(encoding="utf-8-sig")
    assert "<Name>Path</Name>" in proc_text
    assert "<v8:Length>200</v8:Length>" in proc_text

    cfg = (target / "src" / "cf" / "Configuration.xml").read_text(encoding="utf-8-sig")
    assert "<Report>Sales</Report>" in cfg
    assert "<DataProcessor>ImportData</DataProcessor>" in cfg

    from core.project import validate_project

    assert validate_project(target).status == "ok"


@pytest.mark.integration
def test_create_scheduled_job_and_event_subscription_with_real_xmlgen(
    tmp_path: Path,
) -> None:
    jar = resolve_jar()
    java = resolve_java()
    if not jar.found or not java.found:
        pytest.skip("xml-gen jar / Java 17+ недоступны (запустите scripts/fetch-xml-gen.sh)")

    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")

    module = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="CommonModule.Jobs",
            server=True,
        ),
    )
    assert module.status == "ok", module.diagnostics

    catalog = create_metadata(
        target,
        catalog_from_parts(qualified_name="Catalog.Products"),
    )
    assert catalog.status == "ok", catalog.diagnostics

    job = create_metadata(
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
    assert job.status == "ok", job.diagnostics
    job_xml = target / "src" / "cf" / "ScheduledJobs" / "Cleanup.xml"
    assert job_xml.is_file()
    job_text = job_xml.read_text(encoding="utf-8-sig")
    assert "<MethodName>CommonModule.Jobs.Cleanup</MethodName>" in job_text
    assert "<Use>true</Use>" in job_text
    assert "<Description>Nightly</Description>" in job_text
    assert "<Key>cleanup</Key>" in job_text
    assert "<RestartCountOnFailure>5</RestartCountOnFailure>" in job_text
    assert (target / "src" / "cf" / "ScheduledJobs" / "Cleanup" / "Ext" / "Schedule.xml").is_file()

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
    sub_xml = target / "src" / "cf" / "EventSubscriptions" / "ProductsBeforeWrite.xml"
    assert sub_xml.is_file()
    sub_text = sub_xml.read_text(encoding="utf-8-sig")
    assert "<Handler>CommonModule.Jobs.BeforeWrite</Handler>" in sub_text
    assert "<Event>BeforeWrite</Event>" in sub_text
    assert "cfg:Catalog.Products" in sub_text

    cfg = (target / "src" / "cf" / "Configuration.xml").read_text(encoding="utf-8-sig")
    assert "<ScheduledJob>Cleanup</ScheduledJob>" in cfg
    assert "<EventSubscription>ProductsBeforeWrite</EventSubscription>" in cfg

    from core.project import validate_project

    assert validate_project(target).status == "ok"


@pytest.mark.integration
def test_create_http_service_and_web_service_with_real_xmlgen(tmp_path: Path) -> None:
    jar = resolve_jar()
    java = resolve_java()
    if not jar.found or not java.found:
        pytest.skip("xml-gen jar / Java 17+ недоступны (запустите scripts/fetch-xml-gen.sh)")

    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")

    http = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="HTTPService.API",
            synonym="API",
            root_url="api",
            reuse_sessions="DontUse",
            session_max_age=20,
            url_templates={
                "Users": {
                    "template": "/v1/users",
                    "methods": {"Get": "GET", "Create": "POST"},
                }
            },
        ),
    )
    assert http.status == "ok", http.diagnostics
    http_xml = target / "src" / "cf" / "HTTPServices" / "API.xml"
    assert http_xml.is_file()
    http_text = http_xml.read_text(encoding="utf-8-sig")
    assert "<RootURL>api</RootURL>" in http_text
    assert "<Template>/v1/users</Template>" in http_text
    assert "<HTTPMethod>GET</HTTPMethod>" in http_text
    assert (target / "src" / "cf" / "HTTPServices" / "API" / "Ext" / "Module.bsl").is_file()

    web = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="WebService.DataExchange",
            synonym="Обмен",
            namespace="http://www.1c.ru/DataExchange",
            reuse_sessions="DontUse",
            session_max_age=20,
            operations={
                "TestConnection": {
                    "returnType": "xs:boolean",
                    "handler": "ПроверкаПодключения",
                    "parameters": {
                        "ErrorMessage": {"type": "xs:string", "direction": "Out"}
                    },
                }
            },
        ),
    )
    assert web.status == "ok", web.diagnostics
    web_xml = target / "src" / "cf" / "WebServices" / "DataExchange.xml"
    assert web_xml.is_file()
    web_text = web_xml.read_text(encoding="utf-8-sig")
    assert "<Namespace>http://www.1c.ru/DataExchange</Namespace>" in web_text
    assert "<ProcedureName>ПроверкаПодключения</ProcedureName>" in web_text
    assert (target / "src" / "cf" / "WebServices" / "DataExchange" / "Ext" / "Module.bsl").is_file()

    cfg = (target / "src" / "cf" / "Configuration.xml").read_text(encoding="utf-8-sig")
    assert "<HTTPService>API</HTTPService>" in cfg
    assert "<WebService>DataExchange</WebService>" in cfg

    from core.project import validate_project

    assert validate_project(target).status == "ok"
