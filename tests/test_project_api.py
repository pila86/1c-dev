"""Tests for project detect / validate / info."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.main import app
from core.exit_codes import PROJECT_ERROR, SUCCESS
from core.project import detect_manifest, detect_project, validate_project

runner = CliRunner()
FIXTURES = Path(__file__).parent / "fixtures"


def _copy_manifest(tmp_path: Path, fixture_name: str) -> Path:
    dest = tmp_path / "1c.project.yaml"
    shutil.copy(FIXTURES / fixture_name, dest)
    return dest


def test_detect_manifest_in_cwd(tmp_path: Path) -> None:
    _copy_manifest(tmp_path, "valid_1c.project.yaml")
    found = detect_manifest(tmp_path)
    assert found == tmp_path / "1c.project.yaml"


def test_detect_manifest_in_parent(tmp_path: Path) -> None:
    _copy_manifest(tmp_path, "valid_1c.project.yaml")
    child = tmp_path / "nested" / "deep"
    child.mkdir(parents=True)
    found = detect_manifest(child)
    assert found == tmp_path / "1c.project.yaml"


def test_detect_manifest_missing(tmp_path: Path) -> None:
    assert detect_manifest(tmp_path) is None


def test_validate_project_ok(tmp_path: Path) -> None:
    _copy_manifest(tmp_path, "valid_1c.project.yaml")
    result = validate_project(tmp_path)
    assert result.status == "ok"
    assert result.manifest is not None
    assert result.manifest["project"]["name"] == "shop"
    assert result.diagnostics == []


def test_validate_project_invalid(tmp_path: Path) -> None:
    _copy_manifest(tmp_path, "invalid_1c.project.yaml")
    result = validate_project(tmp_path)
    assert result.status == "error"
    assert any(d.get("code") == "1CP003" for d in result.diagnostics)


def test_cli_validate_json_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _copy_manifest(tmp_path, "valid_1c.project.yaml")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["--output", "json", "project", "validate"])
    assert result.exit_code == SUCCESS
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["valid"] is True


def test_cli_validate_json_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _copy_manifest(tmp_path, "invalid_1c.project.yaml")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["--output", "json", "project", "validate"])
    assert result.exit_code == PROJECT_ERROR
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert payload["diagnostics"]
    assert payload["diagnostics"][0]["code"] == "1CP003"


def test_cli_info_json_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _copy_manifest(tmp_path, "valid_1c.project.yaml")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["--output", "json", "project", "info"])
    assert result.exit_code == SUCCESS
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["manifest"]["project"]["type"] == "configuration"


def test_cli_detect_json_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["--output", "json", "project", "detect"])
    assert result.exit_code == PROJECT_ERROR
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert payload["diagnostics"][0]["code"] == "1CP001"


def test_cli_detect_parent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _copy_manifest(tmp_path, "valid_1c.project.yaml")
    child = tmp_path / "sub"
    child.mkdir()
    monkeypatch.chdir(child)
    result = runner.invoke(app, ["--output", "json", "project", "detect"])
    assert result.exit_code == SUCCESS
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["project"]["name"] == "shop"
    assert Path(payload["root"]) == tmp_path


def test_cli_validate_text_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _copy_manifest(tmp_path, "valid_1c.project.yaml")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["project", "validate"])
    assert result.exit_code == SUCCESS
    assert "status: ok" in result.stdout
    assert "manifest: valid" in result.stdout


def test_detect_project_brief_fields(tmp_path: Path) -> None:
    _copy_manifest(tmp_path, "valid_1c.project.yaml")
    result = detect_project(tmp_path)
    payload = result.to_payload()
    assert payload["status"] == "ok"
    assert payload["project"] == {"name": "shop", "type": "configuration"}
