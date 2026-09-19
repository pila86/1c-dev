"""M1 acceptance: init → metadata.create(Catalog) → build → check (Issue #8)."""

from __future__ import annotations

from pathlib import Path

import pytest

from adapters.platform import discover_environment
from adapters.platform_ibcmd.constants import IB_MARKER
from adapters.source.xmlgen.resolve import resolve_jar, resolve_java
from core.build import run_build
from core.check import run_check
from core.metadata import catalog_from_parts, create_metadata
from core.project import init_project


@pytest.mark.integration
def test_m1_acceptance_catalog_via_agent(tmp_path: Path) -> None:
    """Full M1 flow; skip if platform or xml-gen unavailable."""
    jar = resolve_jar()
    java = resolve_java()
    if not jar.found or not java.found:
        pytest.skip("xml-gen jar / Java 17+ недоступны (запустите scripts/fetch-xml-gen.sh)")

    discovery = discover_environment()
    if not discovery.ibcmd.found or discovery.ibcmd.path is None:
        pytest.skip("ibcmd не найден — M1 acceptance пропущен")

    target = tmp_path / "shop"
    target.mkdir()
    init = init_project(target, project_type="configuration", name="Shop")
    assert init.status == "ok", init.to_payload()

    catalog = catalog_from_parts(
        qualified_name="Catalog.Products",
        synonym="Товары",
        attr_specs=["Article:String:50:Артикул"],
    )
    created = create_metadata(target, catalog)
    assert created.status == "ok", created.diagnostics

    products = target / "src" / "cf" / "Catalogs" / "Products.xml"
    assert products.is_file()
    assert "Article" in products.read_text(encoding="utf-8-sig")
    cfg = (target / "src" / "cf" / "Configuration.xml").read_text(encoding="utf-8-sig")
    assert "<Catalog>Products</Catalog>" in cfg

    build = run_build(target)
    assert build.status == "ok", build.to_payload()
    assert (target / ".runtime" / "ib" / IB_MARKER).is_file()

    check = run_check(target)
    assert check.status == "ok", check.to_payload()
