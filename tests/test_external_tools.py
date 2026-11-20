"""Unit tests for External Tools Manager Stage 1 (ADR-033 / #172)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.main import app
from core.exit_codes import RUNTIME_FAILURE, SUCCESS
from core.project.ide import configure_ide
from core.tools.catalog import catalog_root, list_catalog, load_recipe
from core.tools.install import (
    expand_template,
    install_tool,
    is_installed,
    list_installed,
    remove_tool,
    tool_info,
)
from core.tools.paths import share_root, tools_share_dir

runner = CliRunner()


def test_catalog_contains_v8std() -> None:
    root = catalog_root()
    assert (root / "v8std" / "tool.yaml").is_file()
    assert "v8std" in list_catalog()
    recipe = load_recipe("v8std")
    assert recipe.mcp_name == "v8std"
    assert recipe.project_name == "1c-dev-v8std"
    assert "mcp" in recipe.profiles
    assert recipe.guidance_rel == "agent/guidance.md"
    assert (recipe.recipe_dir / "env.default").is_file()
    assert (recipe.recipe_dir / "compose.yaml").is_file()


def test_expand_template_defaults() -> None:
    url = expand_template(
        "http://127.0.0.1:${V8STD_MCP_PORT:-18766}/mcp",
        {},
    )
    assert url == "http://127.0.0.1:18766/mcp"
    url2 = expand_template(
        "http://127.0.0.1:${V8STD_MCP_PORT:-18766}/mcp",
        {"V8STD_MCP_PORT": "19000"},
    )
    assert url2 == "http://127.0.0.1:19000/mcp"


def test_share_paths_xdg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert share_root() == tmp_path / "data" / "1c-dev"
    assert tools_share_dir() == tmp_path / "data" / "1c-dev" / "tools"


def test_install_no_pull_materializes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    result = install_tool("v8std", pull=False)
    assert result.status == "ok", result.diagnostics
    assert result.path is not None
    assert is_installed("v8std")
    assert "v8std" in list_installed()
    info = tool_info("v8std")
    assert info.installed is True
    assert info.mcp_url == "http://127.0.0.1:18766/mcp"
    dest = Path(result.path)
    assert (dest / "tool.yaml").is_file()
    assert (dest / ".env").is_file()
    assert (dest / "compose.yaml").is_file()
    assert (dest / "agent" / "guidance.md").is_file()

    removed = remove_tool("v8std")
    assert removed.status == "ok"
    assert not is_installed("v8std")


def test_install_unknown_tool(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    result = install_tool("no-such-tool", pull=False)
    assert result.status == "error"
    assert any(d.get("code") == "1CX001" for d in result.diagnostics)


def test_cli_tools_list_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    result = runner.invoke(app, ["tools", "list", "--output", "json"])
    assert result.exit_code == SUCCESS, result.stdout
    payload = json.loads(result.stdout)
    ids = {t["id"] for t in payload["tools"]}
    assert "v8std" in ids


def test_cli_tools_info_requires_tool_id() -> None:
    """Typer<0.18 + Click 8.3+ silently passed None; must fail with usage error."""
    result = runner.invoke(app, ["tools", "info"])
    assert result.exit_code != SUCCESS
    combined = (result.stdout or "") + (result.stderr or "")
    assert "Missing argument" in combined or "TOOL_ID" in combined
    assert "TypeError" not in combined
    assert "NoneType" not in combined


def test_cli_tools_install_no_pull(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    result = runner.invoke(
        app, ["tools", "install", "v8std", "--no-pull", "--output", "json"]
    )
    assert result.exit_code == SUCCESS, result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["pulled"] is False


def test_cli_services_status_not_installed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    result = runner.invoke(app, ["services", "status", "v8std", "--output", "json"])
    assert result.exit_code == RUNTIME_FAILURE
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert any(d.get("code") == "1CX002" for d in payload["diagnostics"])


def test_ide_configure_adds_v8std_mcp_and_guidance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    install_tool("v8std", pull=False)
    project = tmp_path / "proj"
    project.mkdir()
    result = configure_ide(project, target="cursor")
    assert result.status == "ok", result.diagnostics
    mcp = json.loads((project / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    assert "v8std" in mcp["mcpServers"]
    assert mcp["mcpServers"]["v8std"]["url"] == "http://127.0.0.1:18766/mcp"
    assert "1c-dev" in mcp["mcpServers"]
    agents = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert "<!-- BEGIN 1c-dev:v8std -->" in agents
    assert "<!-- END 1c-dev:v8std -->" in agents
    rule = project / ".cursor" / "rules" / "ext-v8std-when-to-use.mdc"
    assert rule.is_file()
    assert "managedBy: 1c-dev" in rule.read_text(encoding="utf-8")


def test_ide_configure_removes_guidance_after_remove(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    install_tool("v8std", pull=False)
    project = tmp_path / "proj"
    project.mkdir()
    configure_ide(project, target="cursor")
    remove_tool("v8std")
    result = configure_ide(project, target="cursor")
    assert result.status == "ok", result.diagnostics
    mcp = json.loads((project / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    assert "v8std" not in mcp["mcpServers"]
    agents = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert "<!-- BEGIN 1c-dev:v8std -->" not in agents
    assert not (project / ".cursor" / "rules" / "ext-v8std-when-to-use.mdc").is_file()


def test_cli_toolchain_sync_help() -> None:
    result = runner.invoke(app, ["toolchain", "--help"])
    assert result.exit_code == 0
    assert "sync" in result.stdout
    assert "clean" in result.stdout


@pytest.mark.integration
def test_v8std_install_up_health_down(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Live Docker path: install → up → healthy → down. Skip without docker."""
    import shutil

    if shutil.which("docker") is None:
        pytest.skip("docker не найден")
    # Probe daemon
    import subprocess

    probe = subprocess.run(
        ["docker", "info"],
        capture_output=True,
        check=False,
    )
    if probe.returncode != 0:
        pytest.skip("docker daemon недоступен")

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    install = runner.invoke(app, ["tools", "install", "v8std", "--output", "json"])
    if install.exit_code != SUCCESS:
        payload = json.loads(install.stdout or "{}")
        codes = {d.get("code") for d in payload.get("diagnostics", [])}
        if "1CX006" in codes:
            pytest.skip(f"image pull failed: {install.stdout}")
        assert install.exit_code == SUCCESS, install.stdout

    try:
        up = runner.invoke(app, ["services", "up", "v8std", "--output", "json"])
        assert up.exit_code == SUCCESS, up.stdout
        up_payload = json.loads(up.stdout)
        assert up_payload.get("healthy") is True
        status = runner.invoke(app, ["services", "status", "v8std", "--output", "json"])
        assert status.exit_code == SUCCESS, status.stdout
        assert json.loads(status.stdout).get("healthy") is True
    finally:
        runner.invoke(app, ["services", "down", "v8std", "--output", "json"])
