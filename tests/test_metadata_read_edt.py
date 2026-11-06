"""metadata.list / get / find on source.format: edt (#152)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from adapters.source.edt import CODE_LAYOUT_NOT_EDT, CODE_PATH_NOT_EDT_ROOT
from adapters.source.mdclasses.resolve import resolve_jar, resolve_java
from adapters.source.mdsparrow import EdtWriteResult
from cli.main import app
from core.exit_codes import SUCCESS
from core.metadata import create_metadata, find_metadata, get_metadata, list_metadata
from core.metadata.ir import catalog_from_parts

runner = CliRunner()
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "edt_spike"


def _require_mdreader() -> None:
    java = resolve_java()
    jar = resolve_jar()
    if not java.found or not jar.found:
        pytest.skip(
            "md-reader jar / Java 21+ недоступны (запустите scripts/fetch-md-reader.sh)"
        )


def _copy_edt_fixture(tmp_path: Path) -> Path:
    target = tmp_path / "edt_proj"
    shutil.copytree(FIXTURE, target)
    return target


def test_list_metadata_edt_mock(tmp_path: Path) -> None:
    target = _copy_edt_fixture(tmp_path)

    def fake_read(command: str, source_dir: Path, args: tuple[str, ...]) -> dict[str, Any]:
        assert command == "list"
        assert source_dir == target.resolve()
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

    result = list_metadata(target, read_fn=fake_read)
    assert result.status == "ok"
    assert result.source_path == target.resolve()
    assert result.objects[0]["qname"] == "Catalog.Products"


def test_edt_path_points_to_src_diagnostic(tmp_path: Path) -> None:
    target = _copy_edt_fixture(tmp_path)
    manifest = target / ".1c-dev" / "project.yaml"
    text = manifest.read_text(encoding="utf-8")
    manifest.write_text(text.replace("path: .", "path: src"), encoding="utf-8")

    result = list_metadata(target, read_fn=lambda *_a, **_k: {"status": "ok", "objects": []})
    assert result.status == "error"
    assert any(d.get("code") == CODE_PATH_NOT_EDT_ROOT for d in result.diagnostics)


def test_edt_path_not_layout_diagnostic(tmp_path: Path) -> None:
    target = _copy_edt_fixture(tmp_path)
    bogus = target / "not-edt"
    bogus.mkdir()
    manifest = target / ".1c-dev" / "project.yaml"
    text = manifest.read_text(encoding="utf-8")
    manifest.write_text(text.replace("path: .", "path: not-edt"), encoding="utf-8")

    result = list_metadata(target, read_fn=lambda *_a, **_k: {"status": "ok", "objects": []})
    assert result.status == "error"
    assert any(d.get("code") == CODE_LAYOUT_NOT_EDT for d in result.diagnostics)


def test_create_edt_routed_not_1cm005(tmp_path: Path) -> None:
    """Write path D (#154): format edt больше не 1CM005."""
    target = _copy_edt_fixture(tmp_path)

    def fake_create(edt_root: Path, catalog: Any) -> EdtWriteResult:
        mdo = edt_root / "src" / "Catalogs" / catalog.name / f"{catalog.name}.mdo"
        mdo.parent.mkdir(parents=True)
        mdo.write_text("<mdclass:Catalog/>", encoding="utf-8")
        return EdtWriteResult(
            changed_paths=[f"src/Catalogs/{catalog.name}/{catalog.name}.mdo"]
        )

    result = create_metadata(
        target,
        catalog_from_parts(qualified_name="Catalog.Extra", synonym="Ещё"),
        edt_create_fn=fake_create,
    )
    assert result.status == "ok", result.diagnostics
    assert not any(d.get("code") == "1CM005" for d in result.diagnostics)


@pytest.mark.integration
def test_list_get_find_edt_fixture(tmp_path: Path) -> None:
    _require_mdreader()
    target = _copy_edt_fixture(tmp_path)

    listed = list_metadata(target)
    assert listed.status == "ok", listed.diagnostics
    qnames = {obj["qname"] for obj in listed.objects}
    assert "Catalog.Products" in qnames
    assert listed.source_path == target.resolve()

    got = get_metadata(target, "Catalog.Products")
    assert got.status == "ok", got.diagnostics
    assert got.object == "Catalog.Products"
    assert got.ir is not None
    assert got.ir["type"] == "Catalog"
    assert got.ir["name"] == "Products"
    assert got.ir.get("synonym") == "Товары"

    found = find_metadata(target, "Товар")
    assert found.status == "ok", found.diagnostics
    assert any(obj["qname"] == "Catalog.Products" for obj in found.objects)


@pytest.mark.integration
def test_cli_metadata_list_get_edt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _require_mdreader()
    target = _copy_edt_fixture(tmp_path)
    monkeypatch.chdir(target)

    listed = runner.invoke(app, ["metadata", "list", "--output", "json"])
    assert listed.exit_code == SUCCESS, listed.output
    payload = json.loads(listed.output)
    assert payload["status"] == "ok"
    qnames = {obj["qname"] for obj in payload["objects"]}
    assert "Catalog.Products" in qnames

    got = runner.invoke(app, ["metadata", "get", "Catalog.Products", "--output", "json"])
    assert got.exit_code == SUCCESS, got.output
    get_payload = json.loads(got.output)
    assert get_payload["status"] == "ok"
    assert get_payload["object"] == "Catalog.Products"
    assert get_payload["ir"]["synonym"] == "Товары"
