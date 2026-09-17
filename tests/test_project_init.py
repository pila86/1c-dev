"""Tests for project init."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.main import app
from core.exit_codes import PROJECT_ERROR, SUCCESS
from core.project import init_project, validate_project
from core.project.init import (
    compatibility_mode_for,
    platform_version_for_manifest,
    sanitize_project_name,
)

runner = CliRunner()


def test_sanitize_project_name() -> None:
    assert sanitize_project_name("shop") == "shop"
    assert sanitize_project_name("my shop") == "my_shop"
    assert sanitize_project_name("123") == "C_123"
    assert sanitize_project_name("   ") == "Configuration"


def test_platform_version_for_manifest() -> None:
    assert platform_version_for_manifest("8.3.27.1549") == "8.3.27"
    assert platform_version_for_manifest(None) == "8.3.27"
    assert compatibility_mode_for("8.3.27") == "Version8_3_27"


def test_init_project_ok(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    result = init_project(target, project_type="configuration", name="Shop")
    assert result.status == "ok"
    assert result.path == target / "1c.project.yaml"
    assert (target / "AGENTS.md").is_file()
    assert (target / ".gitignore").is_file()
    assert (target / "src" / "cf" / "Configuration.xml").is_file()
    assert (target / "src" / "cf" / "Languages" / "Русский.xml").is_file()
    assert (target / "build").is_dir()
    assert (target / ".runtime" / "ib").is_dir()
    assert result.manifest is not None
    assert result.manifest["project"]["name"] == "Shop"
    assert result.manifest["project"]["type"] == "configuration"
    assert result.manifest["source"]["path"] == "src/cf"
    assert "1c.project.yaml" in result.created

    validated = validate_project(target)
    assert validated.status == "ok"


def test_init_project_default_name_from_cwd(tmp_path: Path) -> None:
    target = tmp_path / "myapp"
    target.mkdir()
    result = init_project(target, project_type="configuration")
    assert result.status == "ok"
    assert result.manifest is not None
    assert result.manifest["project"]["name"] == "myapp"


def test_init_project_conflict_without_force(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    first = init_project(target, project_type="configuration", name="Shop")
    assert first.status == "ok"
    second = init_project(target, project_type="configuration", name="Shop")
    assert second.status == "error"
    assert any(d.get("code") == "1CP004" for d in second.diagnostics)


def test_init_project_force_overwrites(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    init_project(target, project_type="configuration", name="Shop")
    result = init_project(
        target, project_type="configuration", name="Shop2", force=True
    )
    assert result.status == "ok"
    assert result.manifest is not None
    assert result.manifest["project"]["name"] == "Shop2"


def test_init_project_unsupported_type(tmp_path: Path) -> None:
    result = init_project(tmp_path, project_type="extension")
    assert result.status == "error"
    assert any(d.get("code") == "1CP005" for d in result.diagnostics)
    assert not (tmp_path / "1c.project.yaml").exists()


def test_cli_init_json_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        ["init", "--type", "configuration", "--name", "Demo", "--output", "json"],
    )
    assert result.exit_code == SUCCESS, result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["created"]
    assert (tmp_path / "1c.project.yaml").is_file()


def test_cli_project_init_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        ["--output", "json", "project", "init", "--type", "configuration"],
    )
    assert result.exit_code == SUCCESS, result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"


def test_cli_init_unsupported_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        ["--output", "json", "init", "--type", "extension"],
    )
    assert result.exit_code == PROJECT_ERROR
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert payload["diagnostics"][0]["code"] == "1CP005"


def test_cli_init_conflict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    first = runner.invoke(app, ["init", "--type", "configuration"])
    assert first.exit_code == SUCCESS
    second = runner.invoke(app, ["--output", "json", "init", "--type", "configuration"])
    assert second.exit_code == PROJECT_ERROR
    payload = json.loads(second.stdout)
    assert payload["diagnostics"][0]["code"] == "1CP004"
