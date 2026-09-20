"""Tests for metadata.delete (ADR-011 / #29)."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from adapters.source.xmlgen.resolve import ToolResolve, resolve_jar, resolve_java
from cli.main import app
from core.exit_codes import PROJECT_ERROR, SUCCESS
from core.metadata import catalog_from_parts, create_metadata, delete_metadata, get_metadata
from core.metadata.result import MetadataResult
from core.project import init_project

runner = CliRunner()


def _init_shop_with_catalog(tmp_path: Path) -> Path:
    target = tmp_path / "shop"
    target.mkdir()
    init = init_project(target, project_type="configuration", name="Shop")
    assert init.status == "ok"
    catalogs = target / "src" / "cf" / "Catalogs"
    catalogs.mkdir(parents=True)
    (catalogs / "Products.xml").write_text("<Catalog/>", encoding="utf-8")
    ext = catalogs / "Products" / "Ext"
    ext.mkdir(parents=True)
    (ext / "ObjectModule.bsl").write_text("// stub\n", encoding="utf-8")
    cfg = target / "src" / "cf" / "Configuration.xml"
    text = cfg.read_text(encoding="utf-8-sig")
    text = text.replace(
        "<Language>Русский</Language>",
        "<Language>Русский</Language>\r\n\t\t\t<Catalog>Products</Catalog>",
    )
    cfg.write_text(text, encoding="utf-8-sig", newline="")
    return target


def test_delete_metadata_mock(tmp_path: Path) -> None:
    target = _init_shop_with_catalog(tmp_path)
    products = target / "src" / "cf" / "Catalogs" / "Products.xml"
    assert products.is_file()

    def fake_remove(source_dir: Path, qname: str) -> list[str]:
        assert qname == "Catalog.Products"
        catalog_xml = source_dir / "Catalogs" / "Products.xml"
        sidecar = source_dir / "Catalogs" / "Products"
        removed: list[str] = []
        if catalog_xml.is_file():
            removed.append("Catalogs/Products.xml")
            catalog_xml.unlink()
        if sidecar.is_dir():
            for path in sidecar.rglob("*"):
                if path.is_file():
                    removed.append(path.relative_to(source_dir).as_posix())
            shutil.rmtree(sidecar)
        cfg = source_dir / "Configuration.xml"
        text = cfg.read_text(encoding="utf-8-sig")
        cfg.write_text(
            text.replace("<Catalog>Products</Catalog>", ""),
            encoding="utf-8-sig",
            newline="",
        )
        return removed

    result = delete_metadata(target, "Catalog.Products", remove_fn=fake_remove)
    assert result.status == "ok"
    assert result.object == "Catalog.Products"
    assert any("Catalogs/Products.xml" in p for p in result.deleted)
    assert not products.is_file()
    cfg = (target / "src" / "cf" / "Configuration.xml").read_text(encoding="utf-8-sig")
    assert "<Catalog>Products</Catalog>" not in cfg


def test_delete_not_found(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")
    cfg = target / "src" / "cf" / "Configuration.xml"
    before = hashlib.sha256(cfg.read_bytes()).hexdigest()

    result = delete_metadata(
        target,
        "Catalog.Missing",
        remove_fn=lambda *_a, **_k: [],
    )
    assert result.status == "error"
    assert any(d.get("code") == "1CM008" for d in result.diagnostics)
    assert hashlib.sha256(cfg.read_bytes()).hexdigest() == before


def test_delete_missing_xmlgen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = _init_shop_with_catalog(tmp_path)
    monkeypatch.delenv("ONEC_XMLGEN_JAR", raising=False)
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("JAVA_HOME", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "empty-cache"))

    result = delete_metadata(target, "Catalog.Products")
    assert result.status == "error"
    assert any(d.get("code") == "1CM006" for d in result.diagnostics)


def test_delete_rejects_unknown_type(tmp_path: Path) -> None:
    target = _init_shop_with_catalog(tmp_path)
    result = delete_metadata(
        target,
        "Report.Sales",
        remove_fn=lambda *_a, **_k: [],
    )
    assert result.status == "error"
    assert any(d.get("code") == "1CM002" for d in result.diagnostics)


def test_cli_delete_mock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = _init_shop_with_catalog(tmp_path)
    monkeypatch.chdir(target)

    def fake_delete(start: Path | None, qname: str, **_kw: Any) -> MetadataResult:
        assert qname == "Catalog.Products"
        return MetadataResult(
            status="ok",
            object=qname,
            deleted=["src/cf/Catalogs/Products.xml"],
        )

    monkeypatch.setattr("cli.metadata.delete_metadata", fake_delete)
    result = runner.invoke(
        app,
        ["metadata", "delete", "Catalog.Products", "--output", "json"],
    )
    assert result.exit_code == SUCCESS, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["object"] == "Catalog.Products"
    assert payload["deleted"] == ["src/cf/Catalogs/Products.xml"]


def test_cli_delete_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")
    monkeypatch.chdir(target)
    monkeypatch.setattr(
        "core.metadata.delete.resolve_java",
        lambda: ToolResolve(found=True, path=Path("/usr/bin/java"), version="17"),
    )
    monkeypatch.setattr(
        "core.metadata.delete.resolve_jar",
        lambda: ToolResolve(found=True, path=tmp_path / "xml-gen.jar"),
    )
    result = runner.invoke(
        app,
        ["metadata", "delete", "Catalog.Missing", "--output", "json"],
    )
    assert result.exit_code == PROJECT_ERROR
    payload = json.loads(result.output)
    assert payload["diagnostics"][0]["code"] == "1CM008"


@pytest.mark.integration
def test_delete_with_real_xmlgen(tmp_path: Path) -> None:
    jar = resolve_jar()
    java = resolve_java()
    if not jar.found or not java.found:
        pytest.skip("xml-gen jar / Java 17+ недоступны (запустите scripts/fetch-xml-gen.sh)")

    from adapters.source.mdclasses.resolve import resolve_jar as resolve_md
    from adapters.source.mdclasses.resolve import resolve_java as resolve_md_java

    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")
    created = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="Catalog.Products",
            synonym="Товары",
            attr_specs=["Article:String:50:Артикул"],
        ),
    )
    assert created.status == "ok", created.diagnostics
    products = target / "src" / "cf" / "Catalogs" / "Products.xml"
    assert products.is_file()

    deleted = delete_metadata(target, "Catalog.Products")
    assert deleted.status == "ok", deleted.diagnostics
    assert deleted.deleted
    assert not products.is_file()
    cfg = (target / "src" / "cf" / "Configuration.xml").read_text(encoding="utf-8-sig")
    assert "<Catalog>Products</Catalog>" not in cfg

    again = delete_metadata(target, "Catalog.Products")
    assert again.status == "error"
    assert any(d.get("code") == "1CM008" for d in again.diagnostics)

    md_java = resolve_md_java()
    md_jar = resolve_md()
    if md_java.found and md_jar.found:
        got = get_metadata(target, "Catalog.Products")
        assert got.status == "error"
        assert any(d.get("code") == "1CM008" for d in got.diagnostics)
