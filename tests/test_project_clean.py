"""Tests for project.clean (ADR-021, #76)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from cli.main import app
from core.exit_codes import PROJECT_ERROR, RUNTIME_FAILURE, SUCCESS
from core.project import run_clean
from core.project.constants import (
    CODE_ALREADY_CLEAN,
    CODE_CLIENT_RUNNING,
    CODE_CONFIRM_REQUIRED,
    CODE_MANIFEST_MISSING,
    CODE_RUNTIME_CLEARED,
    CODE_SOURCE_CLEARED,
)
from core.runtime.state import write_state
from tests.helpers_project import bootstrap_configuration_project

runner = CliRunner()


def _seed_dirty_project(tmp_path: Path) -> Path:
    target = tmp_path / "shop"
    target.mkdir()
    init = bootstrap_configuration_project(target, name="Shop", ide_target="all")
    assert init.status == "ok"
    source = target / "src" / "cf"
    source.mkdir(parents=True, exist_ok=True)
    (source / "Configuration.xml").write_text("<Configuration/>\n", encoding="utf-8")
    (source / "Catalogs").mkdir(exist_ok=True)
    (source / "Catalogs" / "Products.xml").write_text("<Catalog/>\n", encoding="utf-8")
    runtime = target / ".1c-dev" / "runtime"
    (runtime / "main").mkdir(parents=True, exist_ok=True)
    (runtime / "main" / "1Cv8.1cd").write_bytes(b"IB")
    (runtime / "ibcmd-data").mkdir(exist_ok=True)
    (runtime / "ibcmd-data" / "tmp").write_text("x", encoding="utf-8")
    write_state(target, pid=4242, debug=False)
    return target


def test_run_clean_requires_yes(tmp_path: Path) -> None:
    target = _seed_dirty_project(tmp_path)
    result = run_clean(target, yes=False)
    assert result.status == "failed"
    assert any(d.get("code") == CODE_CONFIRM_REQUIRED for d in result.diagnostics)
    assert any(d.get("source") == "project" for d in result.diagnostics)
    assert (target / "src" / "cf" / "Configuration.xml").is_file()
    assert (target / ".1c-dev" / "runtime" / "main" / "1Cv8.1cd").is_file()


def test_run_clean_no_manifest(tmp_path: Path) -> None:
    result = run_clean(tmp_path, yes=True)
    assert result.status == "failed"
    assert any(d.get("code") == CODE_MANIFEST_MISSING for d in result.diagnostics)


def test_run_clean_wipes_source_and_runtime(tmp_path: Path) -> None:
    target = _seed_dirty_project(tmp_path)
    agents = target / "AGENTS.md"
    agents_text = agents.read_text(encoding="utf-8")
    manifest = target / ".1c-dev" / "project.yaml"
    manifest_text = manifest.read_text(encoding="utf-8")
    gitignore = target / ".gitignore"
    assert gitignore.is_file()
    cursor_mcp = target / ".cursor" / "mcp.json"
    assert cursor_mcp.is_file()

    result = run_clean(target, yes=True, is_alive=lambda _pid: False)
    assert result.status == "ok"
    assert result.source_cleared is True
    assert result.runtime_cleared is True
    assert any(d.get("code") == CODE_SOURCE_CLEARED for d in result.diagnostics)
    assert any(d.get("code") == CODE_RUNTIME_CLEARED for d in result.diagnostics)
    assert any(d.get("source") == "project" for d in result.diagnostics)
    assert any(d.get("source") == "runtime" for d in result.diagnostics)

    source = target / "src" / "cf"
    assert source.is_dir()
    assert list(source.iterdir()) == []
    assert not (target / ".1c-dev" / "runtime").exists()

    assert manifest.read_text(encoding="utf-8") == manifest_text
    assert agents.read_text(encoding="utf-8") == agents_text
    assert gitignore.is_file()
    assert cursor_mcp.is_file()


def test_run_clean_idempotent(tmp_path: Path) -> None:
    target = _seed_dirty_project(tmp_path)
    first = run_clean(target, yes=True, is_alive=lambda _pid: False)
    assert first.status == "ok"
    second = run_clean(target, yes=True, is_alive=lambda _pid: False)
    assert second.status == "ok"
    assert second.source_cleared is False
    assert second.runtime_cleared is False
    assert any(d.get("code") == CODE_ALREADY_CLEAN for d in second.diagnostics)


def test_run_clean_stops_live_client(tmp_path: Path) -> None:
    target = _seed_dirty_project(tmp_path)
    terminated: list[int] = []

    def fake_alive(pid: int) -> bool:
        return pid == 4242 and 4242 not in terminated

    def fake_terminate(pid: int) -> bool:
        terminated.append(pid)
        return True

    result = run_clean(
        target,
        yes=True,
        is_alive=fake_alive,
        terminate_fn=fake_terminate,
    )
    assert result.status == "ok"
    assert terminated == [4242]
    assert not (target / ".1c-dev" / "runtime").exists()


def test_run_clean_refuses_when_stop_fails(tmp_path: Path) -> None:
    target = _seed_dirty_project(tmp_path)

    result = run_clean(
        target,
        yes=True,
        is_alive=lambda _pid: True,
        terminate_fn=lambda _pid: False,
    )
    assert result.status == "failed"
    assert any(d.get("code") == CODE_CLIENT_RUNNING for d in result.diagnostics)
    assert any(d.get("source") == "runtime" for d in result.diagnostics)
    assert (target / "src" / "cf" / "Configuration.xml").is_file()
    assert (target / ".1c-dev" / "runtime" / "main" / "1Cv8.1cd").is_file()


def test_cli_project_clean_requires_yes(tmp_path: Path, monkeypatch: Any) -> None:
    target = _seed_dirty_project(tmp_path)
    monkeypatch.chdir(target)
    result = runner.invoke(app, ["project", "clean", "--output", "json"])
    assert result.exit_code == RUNTIME_FAILURE
    assert CODE_CONFIRM_REQUIRED in result.stdout
    assert (target / "src" / "cf" / "Configuration.xml").is_file()


def test_cli_project_clean_yes(tmp_path: Path, monkeypatch: Any) -> None:
    target = _seed_dirty_project(tmp_path)
    monkeypatch.chdir(target)
    result = runner.invoke(app, ["project", "clean", "--yes", "--output", "json"])
    assert result.exit_code == SUCCESS
    assert '"status": "ok"' in result.stdout
    assert not (target / ".1c-dev" / "runtime").exists()
    assert list((target / "src" / "cf").iterdir()) == []


def test_cli_project_clean_no_project(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["project", "clean", "--yes", "--output", "json"])
    assert result.exit_code == PROJECT_ERROR
    assert CODE_MANIFEST_MISSING in result.stdout
