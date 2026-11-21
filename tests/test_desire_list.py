"""Tests for project desire-list (.1c-dev/tools.yaml) — ADR-033 Этап 5."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from cli.main import app
from core.exit_codes import RUNTIME_FAILURE, SUCCESS
from core.project.ide import configure_ide
from core.tools.desire import (
    check_desire_list,
    guidance_tool_ids,
    load_desire_list,
    load_guidance_body,
)
from core.tools.install import install_tool

runner = CliRunner()


def _write_desire(root: Path, *tool_ids: str) -> None:
    home = root / ".1c-dev"
    home.mkdir(parents=True, exist_ok=True)
    (home / "tools.yaml").write_text(
        "tools:\n" + "".join(f"  - {tid}\n" for tid in tool_ids),
        encoding="utf-8",
    )


def test_load_desire_list(tmp_path: Path) -> None:
    assert load_desire_list(tmp_path).tool_ids == ()
    _write_desire(tmp_path, "v8std", "bsl-ls")
    desire = load_desire_list(tmp_path)
    assert desire.found is True
    assert desire.tool_ids == ("v8std", "bsl-ls")


def test_check_desire_list_missing_tool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    _write_desire(tmp_path, "v8std", "bsl-ls")
    result = check_desire_list(tmp_path, probe_health=False)
    assert result.status == "error"
    assert any(d.get("code") == "1CX002" for d in result.diagnostics)
    by_id = {item.tool_id: item for item in result.items}
    assert by_id["v8std"].status == "missing"
    assert by_id["bsl-ls"].status == "missing"
    assert by_id["v8std"].desired is True


def test_guidance_includes_desire_only_tool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    _write_desire(tmp_path, "bsl-ls")
    assert "bsl-ls" in guidance_tool_ids(tmp_path)
    body = load_guidance_body("bsl-ls")
    assert body is not None
    assert "bsl-language-server" in body

    project = tmp_path / "proj"
    project.mkdir()
    (project / ".1c-dev").mkdir()
    (project / ".1c-dev" / "tools.yaml").write_text("tools:\n  - bsl-ls\n", encoding="utf-8")
    result = configure_ide(project, target="cursor")
    assert result.status == "ok", result.diagnostics
    agents = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert "<!-- BEGIN 1c-dev:bsl-ls -->" in agents
    mcp = json.loads((project / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    assert "bsl-language-server" not in mcp["mcpServers"]


def test_cli_tools_check_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    _write_desire(tmp_path, "v8std")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["tools", "check", "--output", "json"])
    assert result.exit_code == RUNTIME_FAILURE, result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert any(d.get("code") == "1CX002" for d in payload["diagnostics"])


def test_cli_tools_check_ok_when_installed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from core.services.health import HealthResult

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    install_tool("v8std", pull=False)
    _write_desire(tmp_path, "v8std")
    monkeypatch.chdir(tmp_path)
    with patch(
        "core.tools.desire.check_http",
        return_value=HealthResult(url="http://127.0.0.1:18766/healthz", reachable=True),
    ):
        result = runner.invoke(app, ["tools", "check", "--output", "json"])
    assert result.exit_code == SUCCESS, result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["tools"][0]["installed"] is True