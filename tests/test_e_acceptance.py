"""E-accept: sample create/get/update/delete per wave E0–E8 → build/check (#71)."""

from __future__ import annotations

from pathlib import Path

import pytest

from adapters.platform import discover_environment
from adapters.platform_ibcmd.constants import IB_MARKER
from adapters.source.mdclasses.resolve import resolve_jar as resolve_md_jar
from adapters.source.mdclasses.resolve import resolve_java as resolve_md_java
from adapters.source.xmlgen import EditOp
from adapters.source.xmlgen.resolve import resolve_jar as resolve_xmlgen
from adapters.source.xmlgen.resolve import resolve_java as resolve_java_xml
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


def _ok(result: object) -> None:
    status = getattr(result, "status", None)
    diagnostics = getattr(result, "diagnostics", None)
    assert status == "ok", diagnostics


@pytest.mark.integration
def test_e_acceptance_sample_per_wave(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sample CRUD for E0–E8; skip without platform / xml-gen / md-reader."""
    local_jar = _local_md_reader_jar()
    if local_jar is not None:
        monkeypatch.setenv("ONEC_MDREADER_JAR", str(local_jar))

    md_jar = resolve_md_jar()
    md_java = resolve_md_java()
    if not md_jar.found or not md_java.found:
        pytest.skip(
            "md-reader jar / Java 21+ недоступны (запустите scripts/fetch-md-reader.sh)"
        )
    if not resolve_xmlgen().found or not resolve_java_xml().found:
        pytest.skip(
            "xml-gen jar / Java 17+ недоступны (запустите scripts/fetch-xml-gen.sh)"
        )

    discovery = discover_environment()
    if not discovery.ibcmd.found or discovery.ibcmd.path is None:
        pytest.skip("ibcmd не найден — E-accept пропущен")

    target = tmp_path / "shop"
    target.mkdir()
    init = init_project(target, project_type="configuration", name="Shop")
    assert init.status == "ok", init.to_payload()

    # --- deps ---
    _ok(
        create_metadata(
            target,
            catalog_from_parts(qualified_name="Catalog.Products", synonym="Товары"),
        )
    )
    _ok(
        create_metadata(
            target,
            catalog_from_parts(qualified_name="CommonModule.Jobs", server=True),
        )
    )
    _ok(
        create_metadata(
            target,
            catalog_from_parts(qualified_name="ChartOfAccounts.MainAccounts"),
        )
    )

    # --- E0 CommonModule ---
    _ok(
        create_metadata(
            target,
            catalog_from_parts(
                qualified_name="CommonModule.SalesServer",
                synonym="ПродажиСервер",
                server=True,
                server_call=False,
            ),
        )
    )
    got = get_metadata(target, "CommonModule.SalesServer")
    _ok(got)
    assert got.ir is not None
    assert got.ir["type"] == "CommonModule"
    assert got.ir["server"] is True
    assert got.ir["serverCall"] is False
    _ok(
        update_metadata(
            target,
            "CommonModule.SalesServer",
            [
                EditOp("set-flag", "serverCall=true"),
                EditOp("set-flag", "client=true"),
            ],
        )
    )
    got = get_metadata(target, "CommonModule.SalesServer")
    _ok(got)
    assert got.ir is not None
    assert got.ir["serverCall"] is True
    assert got.ir["clientManagedApplication"] is True

    # --- E1 Subsystem ---
    _ok(
        create_metadata(
            target,
            catalog_from_parts(
                qualified_name="Subsystem.Main",
                synonym="Главная",
                include_in_command_interface=True,
            ),
        )
    )
    got = get_metadata(target, "Subsystem.Main")
    _ok(got)
    assert got.ir is not None
    assert got.ir["type"] == "Subsystem"
    assert got.ir.get("includeInCommandInterface") is True
    _ok(
        update_metadata(
            target,
            "Subsystem.Main",
            [
                EditOp("add-content", "Catalog.Products"),
                EditOp("set-property", "IncludeInCommandInterface=false"),
            ],
        )
    )
    got = get_metadata(target, "Subsystem.Main")
    _ok(got)
    assert got.ir is not None
    assert "Catalog.Products" in (got.ir.get("content") or [])
    assert got.ir.get("includeInCommandInterface") is False

    # --- E2 Constant ---
    _ok(
        create_metadata(
            target,
            catalog_from_parts(
                qualified_name="Constant.VATRate",
                synonym="СтавкаНДС",
                value_type_specs=["Number:5.2"],
            ),
        )
    )
    got = get_metadata(target, "Constant.VATRate")
    _ok(got)
    assert got.ir is not None
    assert got.ir["type"] == "Constant"
    assert got.ir["valueType"]["type"] == "Number"
    _ok(
        update_metadata(
            target,
            "Constant.VATRate",
            [EditOp("modify-property", "Synonym=НоваяСтавка")],
        )
    )
    got = get_metadata(target, "Constant.VATRate")
    _ok(got)
    assert got.ir is not None
    assert got.ir.get("synonym") == "НоваяСтавка"

    # --- E3 Report ---
    _ok(
        create_metadata(
            target,
            catalog_from_parts(
                qualified_name="Report.Sales",
                synonym="Продажи",
                attr_specs=["Period:Date:Период"],
                ts_specs=["Lines:Строки"],
                ts_attr_specs=["Lines.Amount:Number:15.2:Сумма"],
            ),
        )
    )
    got = get_metadata(target, "Report.Sales")
    _ok(got)
    assert got.ir is not None
    assert got.ir["type"] == "Report"
    assert {a.get("name") for a in (got.ir.get("attributes") or [])} >= {"Period"}
    _ok(
        update_metadata(
            target,
            "Report.Sales",
            [
                EditOp("add-attribute", "Cutoff:Number(10,2)"),
                EditOp("modify-property", "Synonym=ОтчётПродажи"),
            ],
        )
    )
    got = get_metadata(target, "Report.Sales")
    _ok(got)
    assert got.ir is not None
    assert got.ir.get("synonym") == "ОтчётПродажи"
    assert {a.get("name") for a in (got.ir.get("attributes") or [])} >= {
        "Period",
        "Cutoff",
    }

    # --- E4 ScheduledJob ---
    _ok(
        create_metadata(
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
    )
    got = get_metadata(target, "ScheduledJob.Cleanup")
    _ok(got)
    assert got.ir is not None
    assert got.ir["type"] == "ScheduledJob"
    assert got.ir["methodName"] == "CommonModule.Jobs.Cleanup"
    assert got.ir["use"] is True
    _ok(
        update_metadata(
            target,
            "ScheduledJob.Cleanup",
            [
                EditOp("modify-property", "Use=false"),
                EditOp("modify-property", "Synonym=НочнаяОчистка"),
            ],
        )
    )
    got = get_metadata(target, "ScheduledJob.Cleanup")
    _ok(got)
    assert got.ir is not None
    assert got.ir["use"] is False
    assert got.ir.get("synonym") == "НочнаяОчистка"

    # --- E5 HTTPService ---
    _ok(
        create_metadata(
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
    )
    got = get_metadata(target, "HTTPService.API")
    _ok(got)
    assert got.ir is not None
    assert got.ir["type"] == "HTTPService"
    assert got.ir["urlTemplates"]["Users"]["template"] == "/v1/users"
    _ok(
        update_metadata(
            target,
            "HTTPService.API",
            [
                EditOp("modify-property", "RootURL=v2"),
                EditOp("modify-property", "Synonym=PublicAPI"),
            ],
        )
    )
    http_xml = (target / "src" / "cf" / "HTTPServices" / "API.xml").read_text(
        encoding="utf-8-sig"
    )
    assert "<RootURL>v2</RootURL>" in http_xml
    got = get_metadata(target, "HTTPService.API")
    _ok(got)
    assert got.ir is not None
    assert got.ir.get("synonym") == "PublicAPI"

    # --- E6 AccountingRegister ---
    _ok(
        create_metadata(
            target,
            catalog_from_parts(
                qualified_name="AccountingRegister.Accounting",
                synonym="Бух",
                chart_of_accounts="ChartOfAccounts.MainAccounts",
                dimension_specs=["Org:String:50"],
                resource_specs=["Sum:Number:15.2"],
            ),
        )
    )
    got = get_metadata(target, "AccountingRegister.Accounting")
    _ok(got)
    assert got.ir is not None
    assert got.ir["type"] == "AccountingRegister"
    assert {d.get("name") for d in (got.ir.get("dimensions") or [])} >= {"Org"}
    _ok(
        update_metadata(
            target,
            "AccountingRegister.Accounting",
            [
                EditOp("add-dimension", "Dept:String(30)"),
                EditOp("modify-property", "Synonym=Учёт"),
            ],
        )
    )
    got = get_metadata(target, "AccountingRegister.Accounting")
    _ok(got)
    assert got.ir is not None
    assert got.ir.get("synonym") == "Учёт"
    assert {d.get("name") for d in (got.ir.get("dimensions") or [])} >= {
        "Org",
        "Dept",
    }

    # --- E7 ChartOfCharacteristicTypes ---
    _ok(
        create_metadata(
            target,
            catalog_from_parts(
                qualified_name="ChartOfCharacteristicTypes.Properties",
                synonym="Свойства",
                value_type_specs=["String:50"],
                attr_specs=["CodeExtra:String:10"],
            ),
        )
    )
    got = get_metadata(target, "ChartOfCharacteristicTypes.Properties")
    _ok(got)
    assert got.ir is not None
    assert got.ir["type"] == "ChartOfCharacteristicTypes"
    assert {a.get("name") for a in (got.ir.get("attributes") or [])} >= {"CodeExtra"}
    _ok(
        update_metadata(
            target,
            "ChartOfCharacteristicTypes.Properties",
            [
                EditOp("add-attribute", "Cutoff:Number(10,2)"),
                EditOp("modify-property", "Synonym=СвойстваОбъектов"),
            ],
        )
    )
    got = get_metadata(target, "ChartOfCharacteristicTypes.Properties")
    _ok(got)
    assert got.ir is not None
    assert got.ir.get("synonym") == "СвойстваОбъектов"
    assert {a.get("name") for a in (got.ir.get("attributes") or [])} >= {
        "CodeExtra",
        "Cutoff",
    }

    # --- E8 Task ---
    _ok(
        create_metadata(
            target,
            catalog_from_parts(
                qualified_name="Task.Todo",
                synonym="Задача",
                attr_specs=["Note:String:50"],
                addressing_attr_specs=["Assignee:String:50"],
            ),
        )
    )
    got = get_metadata(target, "Task.Todo")
    _ok(got)
    assert got.ir is not None
    assert got.ir["type"] == "Task"
    assert {a.get("name") for a in (got.ir.get("attributes") or [])} >= {"Note"}
    assert {
        a.get("name") for a in (got.ir.get("addressingAttributes") or [])
    } >= {"Assignee"}
    _ok(
        update_metadata(
            target,
            "Task.Todo",
            [
                EditOp("add-attribute", "Priority:Number(10,0)"),
                EditOp("modify-property", "Synonym=ЗадачаПользователя"),
            ],
        )
    )
    got = get_metadata(target, "Task.Todo")
    _ok(got)
    assert got.ir is not None
    assert got.ir.get("synonym") == "ЗадачаПользователя"
    assert {a.get("name") for a in (got.ir.get("attributes") or [])} >= {
        "Note",
        "Priority",
    }

    # --- list / find smoke ---
    listed = list_metadata(target)
    _ok(listed)
    qnames = {o["qname"] for o in listed.objects}
    for expected in (
        "CommonModule.SalesServer",
        "Subsystem.Main",
        "Constant.VATRate",
        "Report.Sales",
        "ScheduledJob.Cleanup",
        "HTTPService.API",
        "AccountingRegister.Accounting",
        "ChartOfCharacteristicTypes.Properties",
        "Task.Todo",
    ):
        assert expected in qnames

    found = find_metadata(target, "Продажи")
    _ok(found)
    assert any(o.get("qname") == "Report.Sales" for o in found.objects)

    # --- delete samples + chart/job deps (dependents first) ---
    # ChartOfAccounts from xml-gen is incomplete for ibcmd load; drop it before build.
    for qname, folder, fname in (
        ("Subsystem.Main", "Subsystems", "Main.xml"),
        ("ScheduledJob.Cleanup", "ScheduledJobs", "Cleanup.xml"),
        ("AccountingRegister.Accounting", "AccountingRegisters", "Accounting.xml"),
        ("ChartOfAccounts.MainAccounts", "ChartsOfAccounts", "MainAccounts.xml"),
        (
            "ChartOfCharacteristicTypes.Properties",
            "ChartsOfCharacteristicTypes",
            "Properties.xml",
        ),
        ("Task.Todo", "Tasks", "Todo.xml"),
        ("Constant.VATRate", "Constants", "VATRate.xml"),
        ("Report.Sales", "Reports", "Sales.xml"),
        ("HTTPService.API", "HTTPServices", "API.xml"),
        ("CommonModule.SalesServer", "CommonModules", "SalesServer.xml"),
        ("CommonModule.Jobs", "CommonModules", "Jobs.xml"),
    ):
        deleted = delete_metadata(target, qname)
        _ok(deleted)
        assert not (target / "src" / "cf" / folder / fname).is_file()

    cfg = (target / "src" / "cf" / "Configuration.xml").read_text(encoding="utf-8-sig")
    assert "<Subsystem>Main</Subsystem>" not in cfg
    assert "<ScheduledJob>Cleanup</ScheduledJob>" not in cfg
    assert "<AccountingRegister>Accounting</AccountingRegister>" not in cfg
    assert "<ChartOfAccounts>MainAccounts</ChartOfAccounts>" not in cfg
    assert "<ChartOfCharacteristicTypes>Properties</ChartOfCharacteristicTypes>" not in cfg
    assert "<Task>Todo</Task>" not in cfg
    assert "<Constant>VATRate</Constant>" not in cfg
    assert "<Report>Sales</Report>" not in cfg
    assert "<HTTPService>API</HTTPService>" not in cfg
    assert "<CommonModule>SalesServer</CommonModule>" not in cfg
    assert "<CommonModule>Jobs</CommonModule>" not in cfg

    # Catalog.Products remains — known-good for platform build/check (as in M1)
    assert "<Catalog>Products</Catalog>" in cfg

    build = run_build(target)
    assert build.status == "ok", build.to_payload()
    assert (target / ".1c-dev" / "runtime" / "main" / IB_MARKER).is_file()

    check = run_check(target)
    assert check.status == "ok", check.to_payload()
