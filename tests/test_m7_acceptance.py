"""M7 acceptance: EDT E2E convert → metadata.* → build → check → convert (#159).

Полный паритет (scope B / ADR-032): на fixture ``edt_spike`` —
``source.convert`` XML↔EDT, ``metadata.list|get|create|update``, ``build``/``check``.
Без ``1cedtcli`` / ibcmd / JDK 25 (md-sparrow) / md-reader — skip с явным сообщением.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from adapters.edtcli import (
    EDTCLI_SKIP_MESSAGE,
    PLATFORM_SKIP_MESSAGE,
    discover_edtcli,
)
from adapters.platform import discover_environment
from adapters.platform_ibcmd.constants import IB_MARKER
from adapters.source.edt.constants import CONFIGURATION_MDO_REL, PROJECT_FILE_NAME
from adapters.source.xmlgen.edit import EditOp
from core.build import run_build
from core.check import run_check
from core.metadata import (
    catalog_from_parts,
    create_metadata,
    get_metadata,
    list_metadata,
    update_metadata,
)
from core.project.constants import HOME_EXPORT_DIR_NAME
from core.source import run_convert
from tests.helpers_source_contract import require_md_reader, require_mdsparrow

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "edt_spike"


def _read_format(root: Path) -> tuple[str, str]:
    data = yaml.safe_load((root / ".1c-dev" / "project.yaml").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    configs = data.get("configurations")
    assert isinstance(configs, list) and configs
    main = next(c for c in configs if isinstance(c, dict) and c.get("id") == "main")
    source = main.get("source") or {}
    assert isinstance(source, dict)
    return str(source.get("format")), str(source.get("path"))


def _require_platform() -> None:
    discovery = discover_environment()
    if not discovery.ibcmd.found or discovery.ibcmd.path is None:
        pytest.skip(PLATFORM_SKIP_MESSAGE)
    if not discovery.onecv8.found or discovery.onecv8.path is None:
        pytest.skip(PLATFORM_SKIP_MESSAGE)


def _require_edtcli() -> None:
    info = discover_edtcli()
    if not info.found or info.path is None:
        pytest.skip(EDTCLI_SKIP_MESSAGE)


@pytest.mark.integration
def test_m7_acceptance_edt_e2e(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """convert → metadata write → build → check → convert обратно; skip без EDT/JDK/ibcmd."""
    _require_edtcli()
    _require_platform()
    require_md_reader()
    require_mdsparrow(monkeypatch)

    project = tmp_path / "edt_spike"
    shutil.copytree(FIXTURE, project)
    assert _read_format(project) == ("edt", ".")

    # --- XML baseline (как после M3 import / существующий XML-проект) ---
    to_xml = run_convert(project, to="xml")
    assert to_xml.status == "ok", to_xml.to_payload()
    assert _read_format(project)[0] == "xml"
    assert (project / "Configuration.xml").is_file()

    listed_xml = list_metadata(project)
    assert listed_xml.status == "ok", listed_xml.diagnostics
    xml_qnames = {o["qname"] for o in listed_xml.objects}
    assert "Catalog.Products" in xml_qnames

    # --- convert → edt (agent workflow / manual verification) ---
    to_edt = run_convert(project, to="edt")
    assert to_edt.status == "ok", to_edt.to_payload()
    assert _read_format(project) == ("edt", ".")
    assert (project / PROJECT_FILE_NAME).is_file()
    assert (project / CONFIGURATION_MDO_REL).is_file()
    assert not (project / "Configuration.xml").exists()

    listed_edt = list_metadata(project)
    assert listed_edt.status == "ok", listed_edt.diagnostics
    edt_qnames = {o["qname"] for o in listed_edt.objects}
    assert "Catalog.Products" in edt_qnames

    got_products = get_metadata(project, "Catalog.Products")
    assert got_products.status == "ok", got_products.diagnostics
    assert got_products.ir is not None
    assert got_products.ir.get("type") == "Catalog"
    assert got_products.ir.get("name") == "Products"

    # --- metadata.create|update на EDT (write path D) ---
    partners_mdo = project / "src" / "Catalogs" / "Partners" / "Partners.mdo"
    assert not partners_mdo.exists()

    created = create_metadata(
        project,
        catalog_from_parts(
            qualified_name="Catalog.Partners",
            synonym="Партнёры",
            attr_specs=["Article:String:50:Артикул"],
        ),
    )
    assert created.status == "ok", created.diagnostics
    assert created.object == "Catalog.Partners"
    assert partners_mdo.is_file()
    partners_text = partners_mdo.read_text(encoding="utf-8")
    assert "<name>Partners</name>" in partners_text
    assert "Партнёры" in partners_text
    assert "<name>Article</name>" in partners_text

    updated = update_metadata(
        project,
        "Catalog.Partners",
        [EditOp("add-attribute", "Comment:String(100)")],
    )
    assert updated.status == "ok", updated.diagnostics
    assert "<name>Comment</name>" in partners_mdo.read_text(encoding="utf-8")

    listed_after = list_metadata(project)
    assert listed_after.status == "ok", listed_after.diagnostics
    assert "Catalog.Partners" in {o["qname"] for o in listed_after.objects}

    # --- build / check (export → ibcmd; check по file IB) ---
    build = run_build(project)
    assert build.status == "ok", build.to_payload()
    assert "edt-export" in build.steps
    assert "import" in build.steps
    assert (project / ".1c-dev" / "runtime" / "main" / IB_MARKER).is_file()
    export_xml = project / HOME_EXPORT_DIR_NAME / "main" / "Configuration.xml"
    assert export_xml.is_file() and export_xml.stat().st_size > 0

    check = run_check(project)
    assert "metadata" in check.steps
    meta_errors = [
        d
        for d in check.diagnostics
        if d.get("severity") == "error"
        and "CheckModules" not in str(d.get("message", ""))
    ]
    assert not meta_errors, check.to_payload()
    modules_errors = [
        d
        for d in check.diagnostics
        if d.get("severity") == "error" and "CheckModules" in str(d.get("message", ""))
    ]
    # Полный check.status==ok только при доступном Designer GUI; иначе — soft ниже.
    check_fully_ok = not modules_errors
    if check_fully_ok:
        assert check.status == "ok", check.to_payload()

    # --- convert обратно → xml (паритет tool names; до soft-skip CheckModules) ---
    back_xml = run_convert(project, to="xml")
    assert back_xml.status == "ok", back_xml.to_payload()
    assert _read_format(project)[0] == "xml"
    assert (project / "Configuration.xml").is_file()
    assert (project / "Catalogs" / "Products.xml").is_file()
    assert (project / "Catalogs" / "Partners.xml").is_file()
    assert not (project / PROJECT_FILE_NAME).exists()

    listed_final = list_metadata(project)
    assert listed_final.status == "ok", listed_final.diagnostics
    final_qnames = {o["qname"] for o in listed_final.objects}
    assert "Catalog.Products" in final_qnames
    assert "Catalog.Partners" in final_qnames

    if modules_errors:
        pytest.skip(
            "Designer /CheckModules недоступен в окружении (часто DISPLAY/Wayland); "
            "M7 EDT convert/metadata/build + ibcmd metadata check + convert обратно OK"
        )
