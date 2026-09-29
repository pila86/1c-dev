"""Tests for configuration.* API (#100)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.main import app
from core.configuration import (
    add_configuration,
    get_configuration,
    list_configurations,
    remove_configuration,
    set_default_configuration,
)
from core.exit_codes import PROJECT_ERROR, SUCCESS
from core.project import init_project, validate_project
from core.project.resolve import resolve_config_runtime

runner = CliRunner()


def _empty_scope(tmp_path: Path, name: str = "Shop") -> Path:
    target = tmp_path / "shop"
    target.mkdir()
    result = init_project(target, name=name, ide_target="none")
    assert result.status == "ok", result.diagnostics
    assert result.manifest is not None
    assert result.manifest["configurations"] == []
    assert result.manifest["runtimes"] == []
    assert not (target / "src" / "cf" / "Configuration.xml").exists()
    return target


def test_configuration_add_and_second(tmp_path: Path) -> None:
    target = _empty_scope(tmp_path)
    first = add_configuration(target, name="Shop", config_id="main", source_path="src/cf")
    assert first.status == "ok", first.diagnostics
    assert (target / "src" / "cf" / "Configuration.xml").is_file()
    assert (target / ".1c-dev" / "runtime" / "main").is_dir()
    assert first.manifest is not None
    assert first.manifest["configurations"][0]["id"] == "main"
    assert first.manifest["configurations"][0]["default"] is True
    assert first.manifest["runtimes"][0]["default"] is True

    second = add_configuration(target, name="Buh", config_id="buh")
    assert second.status == "ok", second.diagnostics
    assert (target / "src" / "buh" / "Configuration.xml").is_file()
    assert len(second.manifest["configurations"]) == 2  # type: ignore[index]
    paths = {c["source"]["path"] for c in second.manifest["configurations"]}  # type: ignore[index]
    assert paths == {"src/cf", "src/buh"}
    validated = validate_project(target)
    assert validated.status == "ok"


def test_configuration_list_get_set_default_remove(tmp_path: Path) -> None:
    target = _empty_scope(tmp_path)
    assert (
        add_configuration(
            target, name="Shop", config_id="main", source_path="src/cf"
        ).status
        == "ok"
    )
    assert add_configuration(target, name="Buh", config_id="buh").status == "ok"

    listed = list_configurations(target)
    assert listed.status == "ok"
    assert {c["id"] for c in listed.configurations} == {"main", "buh"}

    got = get_configuration(target, config_id="buh")
    assert got.status == "ok"
    assert got.manifest is not None
    assert got.manifest["configuration"]["id"] == "buh"
    assert got.manifest["runtimes"][0]["id"] == "buh"

    set_def = set_default_configuration(target, config_id="buh")
    assert set_def.status == "ok"
    assert set_def.manifest is not None
    defaults = [c for c in set_def.manifest["configurations"] if c.get("default")]
    assert len(defaults) == 1
    assert defaults[0]["id"] == "buh"

    removed = remove_configuration(target, config_id="main", yes=True, wipe_source=True)
    assert removed.status == "ok"
    assert not (target / "src" / "cf").exists()
    assert removed.manifest is not None
    assert len(removed.manifest["configurations"]) == 1
    assert removed.manifest["configurations"][0]["id"] == "buh"


def test_resolve_empty_suggests_configuration_add(tmp_path: Path) -> None:
    target = _empty_scope(tmp_path)
    result = validate_project(target)
    assert result.status == "ok"
    assert result.manifest is not None
    resolved, diags = resolve_config_runtime(result.manifest)
    assert resolved is None
    assert any("configuration add" in (d.get("suggestion") or "") for d in diags)


def test_init_with_config_sugar(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    result = init_project(target, name="Shop", config="Shop", ide_target="none")
    assert result.status == "ok", result.diagnostics
    assert (target / "src" / "Shop" / "Configuration.xml").is_file()
    assert result.manifest is not None
    assert result.manifest["configurations"][0]["id"] == "Shop"
    assert result.manifest["runtimes"][0]["path"] == ".1c-dev/runtime/Shop"


def test_cli_configuration_add_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _empty_scope(tmp_path)
    monkeypatch.chdir(target)
    add = runner.invoke(
        app,
        [
            "--output",
            "json",
            "configuration",
            "add",
            "--id",
            "main",
            "--name",
            "Shop",
            "--path",
            "src/cf",
        ],
    )
    assert add.exit_code == SUCCESS, add.stdout
    listed = runner.invoke(app, ["--output", "json", "configuration", "list"])
    assert listed.exit_code == SUCCESS, listed.stdout
    payload = json.loads(listed.stdout)
    assert payload["configurations"][0]["id"] == "main"


def test_cli_configuration_remove_requires_yes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _empty_scope(tmp_path)
    assert add_configuration(target, name="Shop", config_id="main").status == "ok"
    monkeypatch.chdir(target)
    result = runner.invoke(
        app, ["--output", "json", "configuration", "remove", "--id", "main"]
    )
    assert result.exit_code == PROJECT_ERROR
    payload = json.loads(result.stdout)
    assert payload["diagnostics"][0]["code"] == "1CC004"
