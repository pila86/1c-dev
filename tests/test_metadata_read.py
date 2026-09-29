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
from tests.helpers_project import bootstrap_configuration_project

runner = CliRunner()


def test_list_metadata_mock(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    init = bootstrap_configuration_project(target, name="Shop")
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
    bootstrap_configuration_project(target, name="Shop")

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
    bootstrap_configuration_project(target, name="Shop")

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
    bootstrap_configuration_project(target, name="Shop")
    monkeypatch.delenv("ONEC_MDREADER_JAR", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "empty-cache"))
    result = list_metadata(target)
    assert result.status == "error"
    assert any(d.get("code") == "1CM006" for d in result.diagnostics)


def test_get_not_found_mock(tmp_path: Path) -> None:
    from adapters.source.mdclasses import MdReaderError

    target = tmp_path / "shop"
    target.mkdir()
    bootstrap_configuration_project(target, name="Shop")

    def fake_read(command: str, source_dir: Path, args: tuple[str, ...]) -> dict[str, Any]:
        raise MdReaderError("Объект не найден: Catalog.Missing", code="1CM008")

    result = get_metadata(target, "Catalog.Missing", read_fn=fake_read)
    assert result.status == "error"
    assert any(d.get("code") == "1CM008" for d in result.diagnostics)


def test_cli_list_mock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    bootstrap_configuration_project(target, name="Shop")
    monkeypatch.chdir(target)

    def fake_list(start: Path | None = None, **_kwargs: Any) -> Any:
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
    bootstrap_configuration_project(target, name="Shop")

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
    bootstrap_configuration_project(target, name="Shop")

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
    bootstrap_configuration_project(target, name="Shop")

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
    """Prefer freshly built md-reader jar from tools/ (Charts / Report full IR)."""
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
    bootstrap_configuration_project(target, name="Shop")

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
    bootstrap_configuration_project(target, name="Shop")

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
    bootstrap_configuration_project(target, name="Shop")

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


def test_get_charts_full_ir_mock(tmp_path: Path) -> None:
    """Smoke: md-reader full IR for Chart* types (#68)."""
    target = tmp_path / "shop"
    target.mkdir()
    bootstrap_configuration_project(target, name="Shop")

    def fake_read_char(
        command: str, source_dir: Path, args: tuple[str, ...]
    ) -> dict[str, Any]:
        assert command == "get"
        assert args == ("ChartOfCharacteristicTypes.Properties",)
        return {
            "status": "ok",
            "object": {
                "type": "ChartOfCharacteristicTypes",
                "name": "Properties",
                "qname": "ChartOfCharacteristicTypes.Properties",
                "valueType": {"type": "String", "length": 50},
                "attributes": [{"name": "CodeExtra", "type": "String", "length": 10}],
                "tabularSections": [
                    {
                        "name": "Extra",
                        "attributes": [{"name": "Note", "type": "String", "length": 20}],
                    }
                ],
            },
        }

    result = get_metadata(
        target, "ChartOfCharacteristicTypes.Properties", read_fn=fake_read_char
    )
    assert result.status == "ok"
    assert result.ir is not None
    assert result.ir["type"] == "ChartOfCharacteristicTypes"
    assert result.ir["valueType"]["length"] == 50
    assert result.ir["attributes"][0]["name"] == "CodeExtra"

    def fake_read_acc(
        command: str, source_dir: Path, args: tuple[str, ...]
    ) -> dict[str, Any]:
        assert args == ("ChartOfAccounts.MainAccounts",)
        return {
            "status": "ok",
            "object": {
                "type": "ChartOfAccounts",
                "name": "MainAccounts",
                "qname": "ChartOfAccounts.MainAccounts",
                "attributes": [{"name": "Extra", "type": "String", "length": 10}],
                "accountingFlags": [{"name": "Currency", "type": "Boolean"}],
                "extDimensionAccountingFlags": [{"name": "Amount", "type": "Boolean"}],
                "tabularSections": [],
            },
        }

    result2 = get_metadata(
        target, "ChartOfAccounts.MainAccounts", read_fn=fake_read_acc
    )
    assert result2.status == "ok"
    assert result2.ir is not None
    assert result2.ir["accountingFlags"][0]["name"] == "Currency"

    def fake_read_calc(
        command: str, source_dir: Path, args: tuple[str, ...]
    ) -> dict[str, Any]:
        assert args == ("ChartOfCalculationTypes.MainCalcs",)
        return {
            "status": "ok",
            "object": {
                "type": "ChartOfCalculationTypes",
                "name": "MainCalcs",
                "qname": "ChartOfCalculationTypes.MainCalcs",
                "attributes": [{"name": "Extra", "type": "String", "length": 10}],
                "tabularSections": [],
            },
        }

    result3 = get_metadata(
        target, "ChartOfCalculationTypes.MainCalcs", read_fn=fake_read_calc
    )
    assert result3.status == "ok"
    assert result3.ir is not None
    assert result3.ir["attributes"][0]["name"] == "Extra"


def test_get_e8_full_ir_mock(tmp_path: Path) -> None:
    """Smoke: md-reader full IR for BP/Task/ExchangePlan/DocumentJournal (#69)."""
    target = tmp_path / "shop"
    target.mkdir()
    bootstrap_configuration_project(target, name="Shop")

    def fake_read_task(
        command: str, source_dir: Path, args: tuple[str, ...]
    ) -> dict[str, Any]:
        assert args == ("Task.Todo",)
        return {
            "status": "ok",
            "object": {
                "type": "Task",
                "name": "Todo",
                "qname": "Task.Todo",
                "attributes": [{"name": "Note", "type": "String", "length": 50}],
                "addressingAttributes": [
                    {"name": "Assignee", "type": "String", "length": 50}
                ],
                "tabularSections": [],
            },
        }

    result = get_metadata(target, "Task.Todo", read_fn=fake_read_task)
    assert result.status == "ok"
    assert result.ir is not None
    assert result.ir["addressingAttributes"][0]["name"] == "Assignee"

    def fake_read_bp(
        command: str, source_dir: Path, args: tuple[str, ...]
    ) -> dict[str, Any]:
        assert args == ("BusinessProcess.Approval",)
        return {
            "status": "ok",
            "object": {
                "type": "BusinessProcess",
                "name": "Approval",
                "qname": "BusinessProcess.Approval",
                "task": "Task.Todo",
                "attributes": [{"name": "Comment", "type": "String", "length": 100}],
                "tabularSections": [],
            },
        }

    result2 = get_metadata(
        target, "BusinessProcess.Approval", read_fn=fake_read_bp
    )
    assert result2.status == "ok"
    assert result2.ir is not None
    assert result2.ir["task"] == "Task.Todo"

    def fake_read_plan(
        command: str, source_dir: Path, args: tuple[str, ...]
    ) -> dict[str, Any]:
        assert args == ("ExchangePlan.Main",)
        return {
            "status": "ok",
            "object": {
                "type": "ExchangePlan",
                "name": "Main",
                "qname": "ExchangePlan.Main",
                "attributes": [{"name": "Extra", "type": "String", "length": 10}],
                "content": [
                    {"metadata": "Catalog.Products", "autoRecord": "Deny"},
                ],
                "tabularSections": [],
            },
        }

    result3 = get_metadata(target, "ExchangePlan.Main", read_fn=fake_read_plan)
    assert result3.status == "ok"
    assert result3.ir is not None
    assert result3.ir["content"][0]["metadata"] == "Catalog.Products"

    def fake_read_journal(
        command: str, source_dir: Path, args: tuple[str, ...]
    ) -> dict[str, Any]:
        assert args == ("DocumentJournal.Docs",)
        return {
            "status": "ok",
            "object": {
                "type": "DocumentJournal",
                "name": "Docs",
                "qname": "DocumentJournal.Docs",
                "registeredDocuments": ["Document.Sales"],
                "columns": [
                    {
                        "name": "Comment",
                        "references": ["Document.Sales.Attribute.Comment"],
                    }
                ],
            },
        }

    result4 = get_metadata(
        target, "DocumentJournal.Docs", read_fn=fake_read_journal
    )
    assert result4.status == "ok"
    assert result4.ir is not None
    assert result4.ir["registeredDocuments"] == ["Document.Sales"]
    assert result4.ir["columns"][0]["name"] == "Comment"


def test_get_scheduled_job_and_event_subscription_full_ir_mock(tmp_path: Path) -> None:
    """Smoke: md-reader full IR for ScheduledJob / EventSubscription (#65)."""
    target = tmp_path / "shop"
    target.mkdir()
    bootstrap_configuration_project(target, name="Shop")

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


def test_get_http_service_and_web_service_full_ir_mock(tmp_path: Path) -> None:
    """Smoke: md-reader full IR for HTTPService / WebService (#66)."""
    target = tmp_path / "shop"
    target.mkdir()
    bootstrap_configuration_project(target, name="Shop")

    def fake_read_http(
        command: str, source_dir: Path, args: tuple[str, ...]
    ) -> dict[str, Any]:
        assert command == "get"
        assert args == ("HTTPService.API",)
        return {
            "status": "ok",
            "object": {
                "type": "HTTPService",
                "name": "API",
                "qname": "HTTPService.API",
                "synonym": "API",
                "urlTemplates": {
                    "Users": {
                        "template": "/v1/users",
                        "methods": {"Get": "UsersGet", "Create": "UsersCreate"},
                    }
                },
            },
        }

    result = get_metadata(target, "HTTPService.API", read_fn=fake_read_http)
    assert result.status == "ok"
    assert result.ir is not None
    assert result.ir["urlTemplates"]["Users"]["template"] == "/v1/users"
    assert result.ir["urlTemplates"]["Users"]["methods"]["Get"] == "UsersGet"

    def fake_read_web(
        command: str, source_dir: Path, args: tuple[str, ...]
    ) -> dict[str, Any]:
        assert args == ("WebService.DataExchange",)
        return {
            "status": "ok",
            "object": {
                "type": "WebService",
                "name": "DataExchange",
                "qname": "WebService.DataExchange",
                "namespace": "http://www.1c.ru/DataExchange",
                "reuseSessions": "DontUse",
                "sessionMaxAge": 20,
                "operations": {
                    "TestConnection": {
                        "handler": "ПроверкаПодключения",
                        "nillable": False,
                        "transactioned": False,
                        "parameters": {
                            "ErrorMessage": {"nillable": False, "direction": "Out"}
                        },
                    }
                },
            },
        }

    result2 = get_metadata(
        target, "WebService.DataExchange", read_fn=fake_read_web
    )
    assert result2.status == "ok"
    assert result2.ir is not None
    assert result2.ir["namespace"] == "http://www.1c.ru/DataExchange"
    assert result2.ir["operations"]["TestConnection"]["handler"] == "ПроверкаПодключения"
    assert (
        result2.ir["operations"]["TestConnection"]["parameters"]["ErrorMessage"][
            "direction"
        ]
        == "Out"
    )


def test_get_accounting_and_calculation_register_full_ir_mock(tmp_path: Path) -> None:
    """Smoke: md-reader full IR for AccountingRegister / CalculationRegister (#67)."""
    target = tmp_path / "shop"
    target.mkdir()
    bootstrap_configuration_project(target, name="Shop")

    def fake_read_acct(
        command: str, source_dir: Path, args: tuple[str, ...]
    ) -> dict[str, Any]:
        assert command == "get"
        assert args == ("AccountingRegister.Accounting",)
        return {
            "status": "ok",
            "object": {
                "type": "AccountingRegister",
                "name": "Accounting",
                "qname": "AccountingRegister.Accounting",
                "synonym": "Бух",
                "dimensions": [{"name": "Org", "type": "String", "length": 50}],
                "resources": [
                    {"name": "Sum", "type": "Number", "precision": 15, "scale": 2}
                ],
            },
        }

    result = get_metadata(
        target, "AccountingRegister.Accounting", read_fn=fake_read_acct
    )
    assert result.status == "ok"
    assert result.ir is not None
    assert result.ir["type"] == "AccountingRegister"
    assert result.ir["dimensions"][0]["name"] == "Org"
    assert result.ir["resources"][0]["name"] == "Sum"

    def fake_read_calc(
        command: str, source_dir: Path, args: tuple[str, ...]
    ) -> dict[str, Any]:
        assert args == ("CalculationRegister.Salary",)
        return {
            "status": "ok",
            "object": {
                "type": "CalculationRegister",
                "name": "Salary",
                "qname": "CalculationRegister.Salary",
                "dimensions": [{"name": "Employee", "type": "String", "length": 50}],
                "resources": [
                    {"name": "Amount", "type": "Number", "precision": 15, "scale": 2}
                ],
                "periodicity": "Month",
            },
        }

    result2 = get_metadata(
        target, "CalculationRegister.Salary", read_fn=fake_read_calc
    )
    assert result2.status == "ok"
    assert result2.ir is not None
    assert result2.ir["periodicity"] == "Month"
    assert result2.ir["dimensions"][0]["name"] == "Employee"


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
    bootstrap_configuration_project(target, name="Shop")

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
    bootstrap_configuration_project(target, name="Shop")

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
    bootstrap_configuration_project(target, name="Shop")

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
def test_http_service_web_service_get_update_delete_roundtrip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create → get full IR → update properties → delete (#66).

    MDClasses gaps (documented):
    - HTTPService: rootURL / reuseSessions / sessionMaxAge not exposed;
      HTTP method verbs missing (get returns handler name).
    - WebService: xdtoPackages / operation returnType / parameter type not
      exposed; TransferDirection from xml-gen (``Output``) often UNKNOWN.
    """
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
    bootstrap_configuration_project(target, name="Shop")

    created = create_metadata(
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
    assert created.status == "ok", created.diagnostics

    got = get_metadata(target, "HTTPService.API")
    assert got.status == "ok", got.diagnostics
    assert got.ir is not None
    assert got.ir["type"] == "HTTPService"
    assert got.ir["name"] == "API"
    assert "urlTemplates" in got.ir
    assert got.ir["urlTemplates"]["Users"]["template"] == "/v1/users"
    assert "Get" in got.ir["urlTemplates"]["Users"]["methods"]
    # Gap: method value is handler name (UsersGet), not HTTP verb GET.
    assert got.ir["urlTemplates"]["Users"]["methods"]["Get"]

    updated = update_metadata(
        target,
        "HTTPService.API",
        [
            EditOp("modify-property", "RootURL=v2"),
            EditOp("modify-property", "Synonym=PublicAPI"),
        ],
    )
    assert updated.status == "ok", updated.diagnostics

    # RootURL not in MDClasses IR — verify XML side-effect; synonym via get.
    http_xml = (target / "src" / "cf" / "HTTPServices" / "API.xml").read_text(
        encoding="utf-8-sig"
    )
    assert "<RootURL>v2</RootURL>" in http_xml

    got2 = get_metadata(target, "HTTPService.API")
    assert got2.status == "ok", got2.diagnostics
    assert got2.ir is not None
    assert got2.ir.get("synonym") == "PublicAPI"

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

    got_w = get_metadata(target, "WebService.DataExchange")
    assert got_w.status == "ok", got_w.diagnostics
    assert got_w.ir is not None
    assert got_w.ir["type"] == "WebService"
    assert got_w.ir["namespace"] == "http://www.1c.ru/DataExchange"
    assert got_w.ir["reuseSessions"] == "DontUse"
    assert got_w.ir["sessionMaxAge"] == 20
    assert got_w.ir["operations"]["TestConnection"]["handler"] == "ПроверкаПодключения"
    # Gap: xml-gen writes TransferDirection=Output; MDClasses 0.20.0 expects Out
    # and often yields UNKNOWN — direction may be absent.
    assert "ErrorMessage" in got_w.ir["operations"]["TestConnection"]["parameters"]

    updated_w = update_metadata(
        target,
        "WebService.DataExchange",
        [
            EditOp("modify-property", "Namespace=http://example.com/exchange"),
            EditOp("modify-property", "Synonym=Exchange"),
        ],
    )
    assert updated_w.status == "ok", updated_w.diagnostics

    got_w2 = get_metadata(target, "WebService.DataExchange")
    assert got_w2.status == "ok", got_w2.diagnostics
    assert got_w2.ir is not None
    assert got_w2.ir["namespace"] == "http://example.com/exchange"
    assert got_w2.ir.get("synonym") == "Exchange"

    deleted_h = delete_metadata(target, "HTTPService.API")
    assert deleted_h.status == "ok", deleted_h.diagnostics
    assert not (target / "src" / "cf" / "HTTPServices" / "API.xml").is_file()

    deleted_w = delete_metadata(target, "WebService.DataExchange")
    assert deleted_w.status == "ok", deleted_w.diagnostics
    assert not (target / "src" / "cf" / "WebServices" / "DataExchange.xml").is_file()

    cfg = (target / "src" / "cf" / "Configuration.xml").read_text(encoding="utf-8-sig")
    assert "<HTTPService>API</HTTPService>" not in cfg
    assert "<WebService>DataExchange</WebService>" not in cfg


@pytest.mark.integration
def test_accounting_calculation_register_get_update_delete_roundtrip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create → get full IR → update dims/resources → delete (#67).

    MDClasses gaps (documented):
    - AccountingRegister: chartOfAccounts not exposed (verify via XML).
    - CalculationRegister: chartOfCalculationTypes not exposed (verify via XML);
      periodicity is returned.
    """
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
    bootstrap_configuration_project(target, name="Shop")

    assert create_metadata(
        target,
        catalog_from_parts(qualified_name="ChartOfAccounts.MainAccounts"),
    ).status == "ok"
    assert create_metadata(
        target,
        catalog_from_parts(qualified_name="ChartOfCalculationTypes.MainCalcs"),
    ).status == "ok"

    created = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="AccountingRegister.Accounting",
            synonym="Бух",
            chart_of_accounts="ChartOfAccounts.MainAccounts",
            dimension_specs=["Org:String:50"],
            resource_specs=["Sum:Number:15.2"],
        ),
    )
    assert created.status == "ok", created.diagnostics

    got = get_metadata(target, "AccountingRegister.Accounting")
    assert got.status == "ok", got.diagnostics
    assert got.ir is not None
    assert got.ir["type"] == "AccountingRegister"
    assert got.ir["name"] == "Accounting"
    dim_names = {d.get("name") for d in (got.ir.get("dimensions") or [])}
    res_names = {r.get("name") for r in (got.ir.get("resources") or [])}
    assert "Org" in dim_names
    assert "Sum" in res_names
    # Gap: chartOfAccounts not in MDClasses IR — present in XML.
    assert "chartOfAccounts" not in got.ir
    acct_xml = (target / "src" / "cf" / "AccountingRegisters" / "Accounting.xml").read_text(
        encoding="utf-8-sig"
    )
    assert "<ChartOfAccounts>ChartOfAccounts.MainAccounts</ChartOfAccounts>" in acct_xml

    updated = update_metadata(
        target,
        "AccountingRegister.Accounting",
        [
            EditOp("add-dimension", "Dept:String(30)"),
            EditOp("add-resource", "Qty:Number(15,3)"),
            EditOp("modify-property", "Synonym=Учёт"),
        ],
    )
    assert updated.status == "ok", updated.diagnostics

    got2 = get_metadata(target, "AccountingRegister.Accounting")
    assert got2.status == "ok", got2.diagnostics
    assert got2.ir is not None
    assert got2.ir.get("synonym") == "Учёт"
    dim_names2 = {d.get("name") for d in (got2.ir.get("dimensions") or [])}
    res_names2 = {r.get("name") for r in (got2.ir.get("resources") or [])}
    assert "Dept" in dim_names2
    assert "Qty" in res_names2

    calc = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="CalculationRegister.Salary",
            synonym="Зарплата",
            chart_of_calculation_types="ChartOfCalculationTypes.MainCalcs",
            dimension_specs=["Employee:String:50"],
            resource_specs=["Amount:Number:15.2"],
        ),
    )
    assert calc.status == "ok", calc.diagnostics

    got_c = get_metadata(target, "CalculationRegister.Salary")
    assert got_c.status == "ok", got_c.diagnostics
    assert got_c.ir is not None
    assert got_c.ir["type"] == "CalculationRegister"
    assert {d.get("name") for d in (got_c.ir.get("dimensions") or [])} >= {"Employee"}
    assert {r.get("name") for r in (got_c.ir.get("resources") or [])} >= {"Amount"}
    assert got_c.ir.get("periodicity") == "Month"
    assert "chartOfCalculationTypes" not in got_c.ir
    calc_xml = (target / "src" / "cf" / "CalculationRegisters" / "Salary.xml").read_text(
        encoding="utf-8-sig"
    )
    assert "ChartOfCalculationTypes.MainCalcs" in calc_xml

    updated_c = update_metadata(
        target,
        "CalculationRegister.Salary",
        [
            EditOp("add-resource", "Bonus:Number(15,2)"),
            EditOp("modify-property", "Synonym=Оклад"),
        ],
    )
    assert updated_c.status == "ok", updated_c.diagnostics

    got_c2 = get_metadata(target, "CalculationRegister.Salary")
    assert got_c2.status == "ok", got_c2.diagnostics
    assert got_c2.ir is not None
    assert got_c2.ir.get("synonym") == "Оклад"
    assert {r.get("name") for r in (got_c2.ir.get("resources") or [])} >= {"Bonus"}

    deleted_a = delete_metadata(target, "AccountingRegister.Accounting")
    assert deleted_a.status == "ok", deleted_a.diagnostics
    assert not (target / "src" / "cf" / "AccountingRegisters" / "Accounting.xml").is_file()

    deleted_c = delete_metadata(target, "CalculationRegister.Salary")
    assert deleted_c.status == "ok", deleted_c.diagnostics
    assert not (target / "src" / "cf" / "CalculationRegisters" / "Salary.xml").is_file()

    cfg = (target / "src" / "cf" / "Configuration.xml").read_text(encoding="utf-8-sig")
    assert "<AccountingRegister>Accounting</AccountingRegister>" not in cfg
    assert "<CalculationRegister>Salary</CalculationRegister>" not in cfg


@pytest.mark.integration
def test_charts_get_update_delete_roundtrip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create → get full IR → update attrs/TS → delete (#68).

    MDClasses 0.20.0: attributes/TS/valueType/accountingFlags exposed for Charts.
    xml-gen meta edit: no dedicated add-accountingFlag ops — flags only on create;
    update covers attributes / tabularSections / Synonym (same as Report).
    """
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
    bootstrap_configuration_project(target, name="Shop")

    created_char = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="ChartOfCharacteristicTypes.Properties",
            synonym="Свойства",
            value_type_specs=["String:50"],
            attr_specs=["CodeExtra:String:10"],
            ts_specs=["Extra"],
            ts_attr_specs=["Extra.Note:String:20"],
        ),
    )
    assert created_char.status == "ok", created_char.diagnostics

    got = get_metadata(target, "ChartOfCharacteristicTypes.Properties")
    assert got.status == "ok", got.diagnostics
    assert got.ir is not None
    assert got.ir["type"] == "ChartOfCharacteristicTypes"
    assert got.ir["name"] == "Properties"
    vt = got.ir.get("valueType") or (got.ir.get("valueTypes") or [None])[0]
    assert vt is not None
    assert vt.get("type") == "String"
    attr_names = {a.get("name") for a in (got.ir.get("attributes") or [])}
    assert "CodeExtra" in attr_names
    sections = {s.get("name") for s in (got.ir.get("tabularSections") or [])}
    assert "Extra" in sections

    updated = update_metadata(
        target,
        "ChartOfCharacteristicTypes.Properties",
        [
            EditOp("add-attribute", "Cutoff:Number(10,2)"),
            EditOp("add-ts-attribute", "Extra.Qty:Number(15,3)"),
            EditOp("modify-property", "Synonym=СвойстваОбъектов"),
        ],
    )
    assert updated.status == "ok", updated.diagnostics

    got2 = get_metadata(target, "ChartOfCharacteristicTypes.Properties")
    assert got2.status == "ok", got2.diagnostics
    assert got2.ir is not None
    assert got2.ir.get("synonym") == "СвойстваОбъектов"
    assert {a.get("name") for a in (got2.ir.get("attributes") or [])} >= {
        "CodeExtra",
        "Cutoff",
    }

    created_acc = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="ChartOfAccounts.MainAccounts",
            synonym="Счета",
            attr_specs=["Extra:String:10"],
            accounting_flag_specs=["Currency:Boolean"],
            ext_dimension_accounting_flag_specs=["Amount:Boolean"],
        ),
    )
    assert created_acc.status == "ok", created_acc.diagnostics

    got_a = get_metadata(target, "ChartOfAccounts.MainAccounts")
    assert got_a.status == "ok", got_a.diagnostics
    assert got_a.ir is not None
    assert got_a.ir["type"] == "ChartOfAccounts"
    flag_names = {f.get("name") for f in (got_a.ir.get("accountingFlags") or [])}
    assert "Currency" in flag_names
    ext_names = {
        f.get("name") for f in (got_a.ir.get("extDimensionAccountingFlags") or [])
    }
    assert "Amount" in ext_names

    updated_a = update_metadata(
        target,
        "ChartOfAccounts.MainAccounts",
        [
            EditOp("add-attribute", "Comment:String(100)"),
            EditOp("modify-property", "Synonym=ПланСчетов"),
        ],
    )
    assert updated_a.status == "ok", updated_a.diagnostics

    got_a2 = get_metadata(target, "ChartOfAccounts.MainAccounts")
    assert got_a2.status == "ok", got_a2.diagnostics
    assert got_a2.ir is not None
    assert got_a2.ir.get("synonym") == "ПланСчетов"
    assert {a.get("name") for a in (got_a2.ir.get("attributes") or [])} >= {
        "Extra",
        "Comment",
    }

    created_c = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="ChartOfCalculationTypes.MainCalcs",
            attr_specs=["Extra:String:10"],
            ts_specs=["ExtraTS"],
            ts_attr_specs=["ExtraTS.Note:String:20"],
        ),
    )
    assert created_c.status == "ok", created_c.diagnostics

    got_c = get_metadata(target, "ChartOfCalculationTypes.MainCalcs")
    assert got_c.status == "ok", got_c.diagnostics
    assert got_c.ir is not None
    assert got_c.ir["type"] == "ChartOfCalculationTypes"
    assert {a.get("name") for a in (got_c.ir.get("attributes") or [])} >= {"Extra"}
    assert {s.get("name") for s in (got_c.ir.get("tabularSections") or [])} >= {
        "ExtraTS"
    }

    updated_c = update_metadata(
        target,
        "ChartOfCalculationTypes.MainCalcs",
        [
            EditOp("add-attribute", "Rate:Number(10,2)"),
            EditOp("modify-property", "Synonym=ВидыРасчёта"),
        ],
    )
    assert updated_c.status == "ok", updated_c.diagnostics

    got_c2 = get_metadata(target, "ChartOfCalculationTypes.MainCalcs")
    assert got_c2.status == "ok", got_c2.diagnostics
    assert got_c2.ir is not None
    assert got_c2.ir.get("synonym") == "ВидыРасчёта"
    assert {a.get("name") for a in (got_c2.ir.get("attributes") or [])} >= {
        "Extra",
        "Rate",
    }

    for qname, folder, fname in (
        (
            "ChartOfCharacteristicTypes.Properties",
            "ChartsOfCharacteristicTypes",
            "Properties.xml",
        ),
        ("ChartOfAccounts.MainAccounts", "ChartsOfAccounts", "MainAccounts.xml"),
        (
            "ChartOfCalculationTypes.MainCalcs",
            "ChartsOfCalculationTypes",
            "MainCalcs.xml",
        ),
    ):
        deleted = delete_metadata(target, qname)
        assert deleted.status == "ok", deleted.diagnostics
        assert not (target / "src" / "cf" / folder / fname).is_file()

    cfg = (target / "src" / "cf" / "Configuration.xml").read_text(encoding="utf-8-sig")
    assert "<ChartOfCharacteristicTypes>Properties</ChartOfCharacteristicTypes>" not in cfg
    assert "<ChartOfAccounts>MainAccounts</ChartOfAccounts>" not in cfg
    assert "<ChartOfCalculationTypes>MainCalcs</ChartOfCalculationTypes>" not in cfg


@pytest.mark.integration
def test_e8_get_update_delete_roundtrip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create → get full IR → update attrs/content → delete (#69).

    MDClasses 0.20.0: attrs/TS/task/addressingAttributes/columns/
    registeredDocuments/content exposed. xml-gen gaps: addressingAttributes and
    columns only on create (no dedicated edit ops); ExchangePlan content via
    add-exchange-content with AutoRecord always Deny; meta compile writes empty
    Content.xml stub (create followup applies content).
    """
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
    bootstrap_configuration_project(target, name="Shop")

    assert create_metadata(
        target, catalog_from_parts(qualified_name="Catalog.Products")
    ).status == "ok"
    assert create_metadata(
        target,
        catalog_from_parts(
            qualified_name="Document.Sales",
            attr_specs=["Comment:String:100"],
        ),
    ).status == "ok"

    created_task = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="Task.Todo",
            synonym="Задача",
            attr_specs=["Note:String:50"],
            addressing_attr_specs=["Assignee:String:50"],
            ts_specs=["Extra"],
            ts_attr_specs=["Extra.Qty:Number:15.3"],
        ),
    )
    assert created_task.status == "ok", created_task.diagnostics

    got_task = get_metadata(target, "Task.Todo")
    assert got_task.status == "ok", got_task.diagnostics
    assert got_task.ir is not None
    assert got_task.ir["type"] == "Task"
    assert {a.get("name") for a in (got_task.ir.get("attributes") or [])} >= {"Note"}
    assert {
        a.get("name") for a in (got_task.ir.get("addressingAttributes") or [])
    } >= {"Assignee"}

    updated_task = update_metadata(
        target,
        "Task.Todo",
        [
            EditOp("add-attribute", "Priority:Number(10,0)"),
            EditOp("modify-property", "Synonym=ЗадачаПользователя"),
        ],
    )
    assert updated_task.status == "ok", updated_task.diagnostics
    got_task2 = get_metadata(target, "Task.Todo")
    assert got_task2.status == "ok", got_task2.diagnostics
    assert got_task2.ir is not None
    assert got_task2.ir.get("synonym") == "ЗадачаПользователя"
    assert {a.get("name") for a in (got_task2.ir.get("attributes") or [])} >= {
        "Note",
        "Priority",
    }

    created_bp = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="BusinessProcess.Approval",
            task="Task.Todo",
            attr_specs=["Comment:String:100"],
        ),
    )
    assert created_bp.status == "ok", created_bp.diagnostics
    got_bp = get_metadata(target, "BusinessProcess.Approval")
    assert got_bp.status == "ok", got_bp.diagnostics
    assert got_bp.ir is not None
    assert got_bp.ir.get("task") == "Task.Todo"

    updated_bp = update_metadata(
        target,
        "BusinessProcess.Approval",
        [EditOp("add-attribute", "Extra:String(20)")],
    )
    assert updated_bp.status == "ok", updated_bp.diagnostics
    got_bp2 = get_metadata(target, "BusinessProcess.Approval")
    assert got_bp2.status == "ok", got_bp2.diagnostics
    assert got_bp2.ir is not None
    assert {a.get("name") for a in (got_bp2.ir.get("attributes") or [])} >= {
        "Comment",
        "Extra",
    }

    created_plan = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="ExchangePlan.Main",
            attr_specs=["Extra:String:10"],
            content=["Catalog.Products"],
        ),
    )
    assert created_plan.status == "ok", created_plan.diagnostics
    got_plan = get_metadata(target, "ExchangePlan.Main")
    assert got_plan.status == "ok", got_plan.diagnostics
    assert got_plan.ir is not None
    content_meta = {
        (c.get("metadata") if isinstance(c, dict) else c)
        for c in (got_plan.ir.get("content") or [])
    }
    assert "Catalog.Products" in content_meta

    updated_plan = update_metadata(
        target,
        "ExchangePlan.Main",
        [
            EditOp("add-attribute", "Comment:String(50)"),
            EditOp("modify-property", "Synonym=ОсновнойОбмен"),
        ],
    )
    assert updated_plan.status == "ok", updated_plan.diagnostics
    got_plan2 = get_metadata(target, "ExchangePlan.Main")
    assert got_plan2.status == "ok", got_plan2.diagnostics
    assert got_plan2.ir is not None
    assert got_plan2.ir.get("synonym") == "ОсновнойОбмен"
    assert {a.get("name") for a in (got_plan2.ir.get("attributes") or [])} >= {
        "Extra",
        "Comment",
    }

    created_journal = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="DocumentJournal.Docs",
            registered_document_specs=["Document.Sales"],
            column_specs=["Comment:Document.Sales.Attribute.Comment"],
        ),
    )
    assert created_journal.status == "ok", created_journal.diagnostics
    got_j = get_metadata(target, "DocumentJournal.Docs")
    assert got_j.status == "ok", got_j.diagnostics
    assert got_j.ir is not None
    assert "Document.Sales" in (got_j.ir.get("registeredDocuments") or [])
    col_names = {c.get("name") for c in (got_j.ir.get("columns") or [])}
    assert "Comment" in col_names

    updated_j = update_metadata(
        target,
        "DocumentJournal.Docs",
        [EditOp("modify-property", "Synonym=ЖурналДокументов")],
    )
    assert updated_j.status == "ok", updated_j.diagnostics
    got_j2 = get_metadata(target, "DocumentJournal.Docs")
    assert got_j2.status == "ok", got_j2.diagnostics
    assert got_j2.ir is not None
    assert got_j2.ir.get("synonym") == "ЖурналДокументов"

    for qname, folder, fname in (
        ("BusinessProcess.Approval", "BusinessProcesses", "Approval.xml"),
        ("Task.Todo", "Tasks", "Todo.xml"),
        ("ExchangePlan.Main", "ExchangePlans", "Main.xml"),
        ("DocumentJournal.Docs", "DocumentJournals", "Docs.xml"),
    ):
        deleted = delete_metadata(target, qname)
        assert deleted.status == "ok", deleted.diagnostics
        assert not (target / "src" / "cf" / folder / fname).is_file()

    cfg = (target / "src" / "cf" / "Configuration.xml").read_text(encoding="utf-8-sig")
    assert "<BusinessProcess>Approval</BusinessProcess>" not in cfg
    assert "<Task>Todo</Task>" not in cfg
    assert "<ExchangePlan>Main</ExchangePlan>" not in cfg
    assert "<DocumentJournal>Docs</DocumentJournal>" not in cfg


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
    init = bootstrap_configuration_project(target, name="Shop")
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
