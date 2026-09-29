"""Tests for project home detect / list / get (ADR-022, #86)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.main import app
from core.exit_codes import SUCCESS
from core.project import (
    detect_manifest,
    detect_project,
    init_project,
    list_projects,
    validate_project,
)
from core.project.constants import (
    CODE_LEGACY_MANIFEST,
    HOME_DIR_NAME,
    HOME_MANIFEST_REL,
    LEGACY_MANIFEST_NAME,
)

runner = CliRunner()
FIXTURES = Path(__file__).parent / "fixtures"


def test_detect_home_manifest_nested(tmp_path: Path) -> None:
    scope = tmp_path / "products" / "shop"
    scope.mkdir(parents=True)
    home = scope / HOME_DIR_NAME
    home.mkdir()
    shutil.copy(FIXTURES / "valid_1c.project.v2.yaml", home / "project.yaml")

    child = scope / "src" / "cf"
    child.mkdir(parents=True)
    found = detect_manifest(child)
    assert found == home / "project.yaml"

    result = detect_project(child)
    assert result.status == "ok"
    assert result.root == scope
    assert result.home == home
    assert result.path == home / "project.yaml"
    assert not any(d.get("code") == CODE_LEGACY_MANIFEST for d in result.diagnostics)


def test_detect_legacy_manifest_with_warning(tmp_path: Path) -> None:
    shutil.copy(FIXTURES / "valid_1c.project.yaml", tmp_path / LEGACY_MANIFEST_NAME)
    child = tmp_path / "nested"
    child.mkdir()
    found = detect_manifest(child)
    assert found == tmp_path / LEGACY_MANIFEST_NAME

    result = detect_project(child)
    assert result.status == "ok"
    assert result.root == tmp_path
    assert result.home is None
    assert any(d.get("code") == CODE_LEGACY_MANIFEST for d in result.diagnostics)
    payload = result.to_payload()
    assert "diagnostics" in payload


def test_detect_prefers_home_over_legacy(tmp_path: Path) -> None:
    shutil.copy(FIXTURES / "valid_1c.project.yaml", tmp_path / LEGACY_MANIFEST_NAME)
    home = tmp_path / HOME_DIR_NAME
    home.mkdir()
    shutil.copy(FIXTURES / "valid_1c.project.v2.yaml", home / "project.yaml")
    found = detect_manifest(tmp_path)
    assert found == home / "project.yaml"
    assert detect_project(tmp_path).home == home


def test_init_writes_schema2_home_layout(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    result = init_project(target, project_type="configuration", name="Shop", ide_target="none")
    assert result.status == "ok"
    assert result.path == target / HOME_DIR_NAME / "project.yaml"
    assert result.root == target
    assert result.home == target / HOME_DIR_NAME
    assert (target / HOME_MANIFEST_REL).is_file()
    assert not (target / LEGACY_MANIFEST_NAME).exists()
    assert (target / ".1c-dev" / "runtime").is_dir()
    assert result.manifest is not None
    assert result.manifest["schema"] == "2"
    assert result.manifest["configurations"] == []
    assert result.manifest["runtimes"] == []
    assert HOME_MANIFEST_REL in result.created


def test_project_get_fields(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(
        target, name="Shop", config="Shop", ide_target="none"
    ).status == "ok"
    result = validate_project(target)
    assert result.status == "ok"
    payload = result.to_payload(include_manifest=True)
    assert payload["root"] == str(target)
    assert payload["home"] == str(target / HOME_DIR_NAME)
    assert payload["manifest_path"] == str(target / HOME_DIR_NAME / "project.yaml")
    assert payload["path"] == payload["manifest_path"]
    assert isinstance(payload["runtimes"], list)
    assert payload["runtimes"][0]["id"] == "Shop"
    assert "manifest" in payload
    assert "summary" in payload
    assert payload["summary"]["defaults"]["configuration"] == "Shop"
    assert payload["summary"]["configurations"][0]["path"] == "src/Shop"


def test_list_projects_nested_monorepo(tmp_path: Path) -> None:
    shop = tmp_path / "products" / "shop"
    buh = tmp_path / "products" / "buh"
    other = tmp_path / "docs"
    for scope in (shop, buh):
        scope.mkdir(parents=True)
        assert init_project(scope, name=scope.name, ide_target="none").status == "ok"
    other.mkdir(parents=True)
    (other / "readme.txt").write_text("x", encoding="utf-8")

    found = list_projects(tmp_path, max_depth=4)
    roots = {r.root for r in found}
    assert shop in roots
    assert buh in roots
    assert other not in roots
    assert all(r.home is not None for r in found)


def test_list_respects_max_depth(tmp_path: Path) -> None:
    deep = tmp_path / "a" / "b" / "c" / "shop"
    deep.mkdir(parents=True)
    assert init_project(deep, name="Shop", ide_target="none").status == "ok"
    assert list_projects(tmp_path, max_depth=2) == []
    assert len(list_projects(tmp_path, max_depth=4)) == 1


def test_cli_project_list_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    shop = tmp_path / "shop"
    shop.mkdir()
    assert init_project(shop, name="Shop", ide_target="none").status == "ok"
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["--output", "json", "project", "list"])
    assert result.exit_code == SUCCESS, result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert len(payload["projects"]) == 1
    assert payload["projects"][0]["home"].endswith(".1c-dev")
