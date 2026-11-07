"""M7 acceptance: EDT E2E (#159) + nested extension EDT → test.run (#164).

#159 (wave 5): fixture ``edt_spike`` — convert → metadata.* → build → check → convert.
#164 (wave 6): fixture ``yaxunit_spike`` — convert ``--extension`` → build → test.run;
``extension add`` format=edt smoke → build; mixed config edt + extension edt.

Без ``1cedtcli`` / ibcmd / 1cv8 / yaxunit.cfe / JDK 25 (md-sparrow) / md-reader —
skip с явным сообщением.
"""

from __future__ import annotations

import shutil
import urllib.error
from pathlib import Path
from typing import Any

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
from core.exit_codes import TEST_FAILURE
from core.extension import add_extension
from core.metadata import (
    catalog_from_parts,
    create_metadata,
    get_metadata,
    list_metadata,
    update_metadata,
)
from core.project.constants import HOME_EXPORT_DIR_NAME
from core.source import run_convert
from core.test import run_tests
from core.toolchain.cache import tools_cache_dir
from core.toolchain.fetchers.yaxunit import fetch_yaxunit
from core.toolchain.manifest import load_manifest
from core.toolchain.resolve import resolve_yaxunit_cfe
from tests.helpers_project import bootstrap_configuration_project
from tests.helpers_source_contract import require_md_reader, require_mdsparrow

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "edt_spike"
YAXUNIT_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "yaxunit_spike"


def _read_format(root: Path) -> tuple[str, str]:
    data = yaml.safe_load((root / ".1c-dev" / "project.yaml").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    configs = data.get("configurations")
    assert isinstance(configs, list) and configs
    main = next(c for c in configs if isinstance(c, dict) and c.get("id") == "main")
    source = main.get("source") or {}
    assert isinstance(source, dict)
    return str(source.get("format")), str(source.get("path"))


def _read_extension_format(root: Path, ext_id: str) -> tuple[str, str]:
    data = yaml.safe_load((root / ".1c-dev" / "project.yaml").read_text(encoding="utf-8"))
    for conf in data["configurations"]:
        for ext in conf.get("extensions") or []:
            if isinstance(ext, dict) and ext.get("id") == ext_id:
                source = ext.get("source") or {}
                return str(source.get("format")), str(source.get("path"))
    raise AssertionError(f"extension {ext_id!r} not in manifest")


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


def _ensure_yaxunit_cfe() -> Path:
    """Return YAxUnit.cfe: cache / ONEC_YAXUNIT_CFE, else soft fetch (tools sync path)."""
    resolved = resolve_yaxunit_cfe()
    if resolved.found and resolved.path is not None:
        return resolved.path

    env_name = resolved.env_name or "ONEC_YAXUNIT_CFE"
    skip_msg = (
        f"YAxUnit.cfe не найден — выполните 1c-dev tools sync "
        f"или задайте {env_name}=/path/to/YAxUnit.cfe"
    )
    manifest = load_manifest()
    spec = manifest.get("yaxunit")
    if spec is None:
        pytest.skip(skip_msg)

    try:
        path, _diags = fetch_yaxunit(spec, tools_cache_dir(), quiet=True)
    except (OSError, urllib.error.URLError) as exc:
        pytest.skip(f"{skip_msg} ({exc})")

    if path is None or not path.is_file():
        resolved = resolve_yaxunit_cfe()
        if resolved.found and resolved.path is not None:
            return resolved.path
        pytest.skip(skip_msg)
    return path


def _copy_yaxunit_spike(tmp_path: Path) -> Path:
    project = tmp_path / "yaxunit_spike"
    shutil.copytree(YAXUNIT_FIXTURE, project, ignore=shutil.ignore_patterns("run_yaxunit.py"))
    return project


def _assert_test_run_with_ensure(project: Path) -> None:
    """Same contract as M5: intentional failures + runner ensure ok (ADR-029)."""
    run_result = run_tests(project)
    payload = run_result.to_payload()
    assert run_result.status == "failed", payload
    assert run_result.exit_code == TEST_FAILURE, payload
    assert (run_result.failed or 0) + (run_result.error or 0) > 0, payload
    assert (run_result.passed or 0) > 0, payload

    ensure = run_result.runner_ensure
    assert isinstance(ensure, dict), payload
    assert ensure.get("status") == "ok", payload
    assert ensure.get("cfePath"), payload
    assert ensure.get("loaded") is True, payload


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


@pytest.mark.integration
def test_m7_acceptance_nested_extension_edt_test_run(tmp_path: Path) -> None:
    """#164: convert --extension → build → test.run; YAXUNIT через ensure."""
    _require_edtcli()
    _require_platform()
    yaxunit_cfe = _ensure_yaxunit_cfe()
    assert yaxunit_cfe.is_file()

    project = _copy_yaxunit_spike(tmp_path)
    assert _read_format(project) == ("xml", "src/main")
    assert _read_extension_format(project, "test_ext1") == ("xml", "src/cfe/test_ext1")
    assert _read_extension_format(project, "test_ext2") == ("xml", "src/cfe/test_ext2")

    for ext_id in ("test_ext1", "test_ext2"):
        converted = run_convert(project, to="edt", extension_id=ext_id)
        assert converted.status == "ok", converted.to_payload()
        assert converted.extension_id == ext_id
        assert converted.to_format == "edt"
        fmt, path = _read_extension_format(project, ext_id)
        assert fmt == "edt"
        assert path == f"src/cfe/{ext_id}"
        ext_root = project / path
        assert (ext_root / PROJECT_FILE_NAME).is_file()
        assert (ext_root / CONFIGURATION_MDO_REL).is_file()
        assert not (ext_root / "Configuration.xml").exists()

    # Config stays XML (только --extension).
    assert _read_format(project) == ("xml", "src/main")
    assert (project / "src" / "main" / "Configuration.xml").is_file()

    build = run_build(project)
    assert build.status == "ok", build.to_payload()
    assert "edt-export:Tests1" in build.steps
    assert "edt-export:Tests2" in build.steps
    assert "import:Tests1" in build.steps
    assert "import:Tests2" in build.steps
    assert (project / ".1c-dev" / "runtime" / "main" / IB_MARKER).is_file()
    for ext_id in ("test_ext1", "test_ext2"):
        ext_xml = (
            project / HOME_EXPORT_DIR_NAME / "main" / "ext" / ext_id / "Configuration.xml"
        )
        assert ext_xml.is_file() and ext_xml.stat().st_size > 0

    _assert_test_run_with_ensure(project)


@pytest.mark.integration
def test_m7_acceptance_mixed_config_and_extension_edt_test_run(tmp_path: Path) -> None:
    """#164: config edt + extension edt не ломает test.run."""
    _require_edtcli()
    _require_platform()
    yaxunit_cfe = _ensure_yaxunit_cfe()
    assert yaxunit_cfe.is_file()

    project = _copy_yaxunit_spike(tmp_path)

    to_edt_cfg = run_convert(project, to="edt")
    assert to_edt_cfg.status == "ok", to_edt_cfg.to_payload()
    assert _read_format(project) == ("edt", "src/main")
    assert (project / "src" / "main" / PROJECT_FILE_NAME).is_file()
    assert not (project / "src" / "main" / "Configuration.xml").exists()

    for ext_id in ("test_ext1", "test_ext2"):
        converted = run_convert(project, to="edt", extension_id=ext_id)
        assert converted.status == "ok", converted.to_payload()
        assert _read_extension_format(project, ext_id)[0] == "edt"

    build = run_build(project)
    assert build.status == "ok", build.to_payload()
    assert "edt-export" in build.steps
    assert "edt-export:Tests1" in build.steps
    assert "edt-export:Tests2" in build.steps
    assert (project / ".1c-dev" / "runtime" / "main" / IB_MARKER).is_file()

    _assert_test_run_with_ensure(project)


@pytest.mark.integration
def test_m7_acceptance_extension_add_format_edt_build(tmp_path: Path) -> None:
    """#164 smoke: extension add format=edt → build (#163)."""
    _require_edtcli()
    _require_platform()

    project = tmp_path / "shop"
    project.mkdir()
    boot = bootstrap_configuration_project(project, name="Shop")
    assert boot.status == "ok", boot.diagnostics

    added = add_extension(
        project,
        ext_id="custom",
        name="CustomExt",
        purpose="product",
        format="edt",
    )
    assert added.status == "ok", added.diagnostics

    ext = project / "src" / "cfe" / "custom"
    assert (ext / PROJECT_FILE_NAME).is_file()
    assert (ext / CONFIGURATION_MDO_REL).is_file()
    assert not (ext / "Configuration.xml").exists()

    data: dict[str, Any] = yaml.safe_load(
        (project / ".1c-dev" / "project.yaml").read_text(encoding="utf-8")
    )
    exts = data["configurations"][0]["extensions"]
    assert exts[0]["source"] == {"format": "edt", "path": "src/cfe/custom"}

    build = run_build(project)
    assert build.status == "ok", build.to_payload()
    assert "edt-export:CustomExt" in build.steps
    assert "import:CustomExt" in build.steps
    assert "apply:CustomExt" in build.steps
    ext_xml = (
        project / HOME_EXPORT_DIR_NAME / "main" / "ext" / "custom" / "Configuration.xml"
    )
    assert ext_xml.is_file() and ext_xml.stat().st_size > 0
