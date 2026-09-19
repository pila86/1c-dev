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


@pytest.mark.integration
def test_read_with_real_md_reader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    java = resolve_java()
    jar = resolve_jar()
    if not java.found or not jar.found:
        pytest.skip(
            "md-reader jar / Java 17+ недоступны (запустите scripts/fetch-md-reader.sh)"
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
