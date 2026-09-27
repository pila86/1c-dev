"""M3 acceptance: CF import round-trip → list/get → ide configure → docs → build/check (#52)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from adapters.docs.hbk import find_hbk
from adapters.docs.resolve import resolve_jar as resolve_docs_jar
from adapters.docs.resolve import resolve_java as resolve_docs_java
from adapters.platform import discover_environment
from adapters.platform_ibcmd.constants import IB_MARKER
from adapters.source.mdclasses.resolve import resolve_jar as resolve_md_jar
from adapters.source.mdclasses.resolve import resolve_java as resolve_md_java
from adapters.source.xmlgen.resolve import resolve_jar as resolve_xmlgen
from adapters.source.xmlgen.resolve import resolve_java as resolve_java_xml
from core.build import run_build
from core.check import run_check
from core.docs import get_docs, search_docs
from core.import_cf import run_import
from core.metadata import catalog_from_parts, create_metadata, get_metadata, list_metadata
from core.project import MANIFEST_NAME, configure_ide, init_project


@pytest.mark.integration
def test_m3_acceptance_import_ide_docs(tmp_path: Path) -> None:
    """Full M3 product-adopt flow; skip if platform / xml-gen / md-reader unavailable."""
    if not resolve_xmlgen().found or not resolve_java_xml().found:
        pytest.skip(
            "xml-gen jar / Java 17+ недоступны (запустите scripts/fetch-xml-gen.sh "
            "или 1c-dev tools sync)"
        )

    md_jar = resolve_md_jar()
    md_java = resolve_md_java()
    if not md_jar.found or not md_java.found:
        pytest.skip(
            "md-reader jar / Java 21+ недоступны (запустите scripts/fetch-md-reader.sh "
            "или 1c-dev tools sync)"
        )

    discovery = discover_environment()
    if not discovery.ibcmd.found or discovery.ibcmd.path is None:
        pytest.skip("ibcmd не найден — M3 acceptance пропущен")

    # --- source project with a Catalog ---
    source = tmp_path / "shop"
    source.mkdir()
    init = init_project(source, project_type="configuration", name="Shop")
    assert init.status == "ok", init.to_payload()

    created = create_metadata(
        source,
        catalog_from_parts(
            qualified_name="Catalog.Products",
            synonym="Товары",
            attr_specs=["Article:String:50:Артикул"],
        ),
    )
    assert created.status == "ok", created.diagnostics

    build_cf = run_build(source, artifact="cf")
    assert build_cf.status == "ok", build_cf.to_payload()
    built_cf = source / (build_cf.artifact or "build/out/configuration.cf")
    assert built_cf.is_file()
    cf_path = tmp_path / "configuration.cf"
    cf_path.write_bytes(built_cf.read_bytes())

    # --- import into a fresh project root ---
    imported = tmp_path / "imported"
    imported.mkdir()
    imported_result = run_import(imported, from_path=cf_path, break_support=True)
    assert imported_result.status == "ok", imported_result.to_payload()
    assert "export" in imported_result.steps
    assert (imported / MANIFEST_NAME).is_file()
    assert (imported / "src" / "cf" / "Configuration.xml").is_file()
    assert not (imported / "AGENTS.md").exists()

    # --- metadata visible after import ---
    listed = list_metadata(imported)
    assert listed.status == "ok", listed.diagnostics
    qnames = {o["qname"] for o in listed.objects}
    assert "Catalog.Products" in qnames

    got = get_metadata(imported, "Catalog.Products")
    assert got.status == "ok", got.diagnostics
    assert got.ir is not None
    assert got.ir.get("type") == "Catalog"
    assert got.ir.get("name") == "Products"
    attrs = {
        a.get("name"): a
        for a in (got.ir.get("attributes") or [])
        if isinstance(a, dict)
    }
    assert "Article" in attrs

    # --- ide configure (agent artifacts after import) ---
    ide = configure_ide(imported, target="cursor")
    assert ide.status == "ok", ide.to_payload()
    assert (imported / "AGENTS.md").is_file()
    mcp_path = imported / ".cursor" / "mcp.json"
    assert mcp_path.is_file()
    mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert set(mcp["mcpServers"]) == {"1c-dev", "bsl-language-server"}

    # --- docs soft: assert when jar + HBK present; else do not fail E2E ---
    docs_jar = resolve_docs_jar()
    docs_java = resolve_docs_java()
    hbk = find_hbk(discovery.platform.path)
    if docs_jar.found and docs_java.found and hbk.found:
        search = search_docs(imported, "Массив", limit=5)
        assert search.status == "ok", search.to_payload()
        assert isinstance(search.hits, list)

        entry = get_docs(imported, "Массив")
        assert entry.status == "ok", entry.to_payload()
        assert entry.entry is not None
        assert entry.entry.get("qualifiedName") == "Массив"

    # --- build / check on imported source ---
    build = run_build(imported)
    assert build.status == "ok", build.to_payload()
    assert (imported / ".runtime" / "ib" / IB_MARKER).is_file()

    check = run_check(imported)
    assert check.status == "ok", check.to_payload()
