"""Unit tests for External Tools Manager (ADR-033 / #172 / #175)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from cli.main import app
from core.exit_codes import RUNTIME_FAILURE, SUCCESS
from core.project.ide import configure_ide
from core.services.compose import ComposeCommandResult
from core.services.health import HealthResult
from core.services.state import load_state, state_path
from core.tools.catalog import catalog_root, list_catalog, load_recipe
from core.tools.install import (
    expand_template,
    install_tool,
    is_installed,
    list_installed,
    remove_tool,
    resolve_env_vars,
    tool_info,
)
from core.tools.paths import services_share_dir, share_root, tools_share_dir

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


def test_catalog_bsl_ls_stage7() -> None:
    root = catalog_root()
    assert (root / "bsl-ls" / "tool.yaml").is_file()
    assert "bsl-ls" in list_catalog()
    recipe = load_recipe("bsl-ls")
    assert recipe.mcp_name == "bsl-language-server"
    assert recipe.runtime.get("type") == "process"
    assert recipe.source_type == "github-release"
    assert recipe.project_name == "1c-dev-bsl-ls"
    assert (recipe.recipe_dir / "env.default").is_file()
    assert (recipe.recipe_dir / "agent" / "guidance.md").is_file()


def test_catalog_bsl_search_stage3() -> None:
    root = catalog_root()
    assert (root / "bsl-search" / "tool.yaml").is_file()
    assert "bsl-search" in list_catalog()
    recipe = load_recipe("bsl-search")
    assert recipe.is_scaffold is False
    assert recipe.mcp_name == "bsl-search"
    assert recipe.compose_file == "compose.yaml"
    assert recipe.compose_build is True
    assert recipe.source_type == "git"
    assert recipe.index_config.get("provider") == "huggingface"
    assert recipe.project_name == "1c-dev-bsl-search"
    assert (recipe.recipe_dir / "env.default").is_file()
    assert (recipe.recipe_dir / "compose.yaml").is_file()
    assert "REPLACE_ME" not in (recipe.recipe_dir / "env.default").read_text(
        encoding="utf-8"
    )
    assert (recipe.recipe_dir / "agent" / "guidance.md").is_file()


def test_install_bsl_ls_no_pull_materializes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    result = install_tool("bsl-ls", pull=False)
    assert result.status == "ok", result.diagnostics
    assert is_installed("bsl-ls")
    dest = Path(result.path or "")
    assert (dest / "tool.yaml").is_file()
    assert (dest / ".env").is_file()
    assert not any(
        d.get("code") == "1CX006"
        for d in result.diagnostics
        if d.get("severity") == "error"
    )
    assert any("no-pull" in (d.get("message") or "") for d in result.diagnostics)


def test_services_up_bsl_ls_process_mock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from core.services.manager import service_up

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    install_tool("bsl-ls", pull=False)
    jar = tools_share_dir() / "bsl-ls" / "lib" / "bsl-language-server.jar"
    jar.parent.mkdir(parents=True, exist_ok=True)
    jar.write_bytes(b"pk\x03\x04")

    with (
        patch("core.services.process.start_process", return_value=(True, [])),
        patch(
            "core.services.health.check_http",
            return_value=HealthResult(url="http://127.0.0.1:18767/mcp", reachable=True),
        ),
        patch("core.services.manager._wait_health", return_value=True),
    ):
        up = service_up("bsl-ls")
    assert up.status == "ok", up.diagnostics
    assert up.healthy is True
    assert up.mcp_url == "http://127.0.0.1:18767/mcp"


def test_ide_configure_bsl_ls_http_when_installed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    install_tool("bsl-ls", pull=False)
    project = tmp_path / "proj"
    project.mkdir()
    with patch(
        "core.services.health.check_http",
        return_value=HealthResult(url="http://127.0.0.1:18767/mcp", reachable=True),
    ):
        result = configure_ide(project, target="cursor")
    assert result.status == "ok", result.diagnostics
    mcp = json.loads((project / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["bsl-language-server"] == {
        "url": "http://127.0.0.1:18767/mcp",
    }
    assert not any(d.get("code") == "1CP009" for d in result.diagnostics)


def test_install_bsl_search_no_pull_materializes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    result = install_tool("bsl-search", pull=False)
    assert result.status == "ok", result.diagnostics
    assert is_installed("bsl-search")
    dest = Path(result.path or "")
    assert (dest / "compose.yaml").is_file()
    assert (dest / ".env").is_file()
    assert any("no-pull" in (d.get("message") or "") for d in result.diagnostics)


def test_normalize_bsl_row() -> None:
    from core.tools.bsl_search_index import normalize_row

    row = normalize_row(
        {
            "repo": "demo",
            "file": "a.bsl",
            "name": "Тест",
            "body": "Процедура Тест()\nКонецПроцедуры\n",
            "params": "",
            "doc": "",
        }
    )
    assert row is not None
    assert row["id"]
    assert row["exact_hash"]
    assert "Имя: Тест" in row["search_text"]
    assert normalize_row({"name": "x", "body": ""}) is None


def test_bulk_load_skips_nonempty_index(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from core.tools import bsl_search_index as idx

    jsonl = tmp_path / "c.jsonl"
    jsonl.write_text(
        json.dumps({"id": "a", "name": "A", "body": "x"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(idx, "_es_request", lambda *a, **k: {"version": {"number": "8.15.3"}})
    monkeypatch.setattr(idx, "es_doc_count", lambda *a, **k: 42)
    ok, count, diags = idx.bulk_load_corpus(
        jsonl,
        base_url="http://127.0.0.1:19200",
        index="bsl-methods",
        force=False,
    )
    assert ok is True
    assert count == 42
    assert any("skip bulk" in (d.get("message") or "") for d in diags)


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
    assert services_share_dir() == tmp_path / "data" / "1c-dev" / "services"


def test_resolve_env_vars_overlays_known_keys(tmp_path: Path) -> None:
    tool_dir = tmp_path / "tool"
    tool_dir.mkdir()
    (tool_dir / "env.default").write_text(
        "FOO_PORT=1\nFOO_IMAGE=img:tag\n",
        encoding="utf-8",
    )
    (tool_dir / ".env").write_text("FOO_PORT=2\n", encoding="utf-8")
    merged = resolve_env_vars(
        tool_dir,
        environ={"FOO_PORT": "9", "FOO_IMAGE": "from-env", "UNRELATED": "x"},
    )
    assert merged["FOO_PORT"] == "9"
    assert merged["FOO_IMAGE"] == "from-env"
    assert "UNRELATED" not in merged


def test_service_up_persists_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    install_tool("v8std", pull=False)

    compose_ok = ComposeCommandResult(
        ok=True, returncode=0, stdout="", stderr="", diagnostics=[]
    )
    with (
        patch("core.services.manager.docker_available", return_value=True),
        patch("core.services.manager.port_in_use", return_value=False),
        patch("core.services.manager.run_compose", return_value=compose_ok),
        patch(
            "core.services.manager.check_http",
            return_value=HealthResult(
                url="http://127.0.0.1:18766/healthz",
                reachable=True,
                status_code=200,
            ),
        ),
    ):
        from core.services.manager import service_up

        result = service_up("v8std", wait_health_sec=1.0)
    assert result.status == "ok"
    assert result.project_name == "1c-dev-v8std"
    assert state_path().is_file()
    stacks = load_state()
    assert "v8std" in stacks
    assert stacks["v8std"].last_action == "up"
    assert stacks["v8std"].healthy is True
    assert stacks["v8std"].labels.get("managed-by") == "1c-dev"


def test_cli_services_restart_help() -> None:
    result = runner.invoke(app, ["services", "--help"])
    assert result.exit_code == 0
    assert "restart" in result.stdout


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


def test_install_pull_falls_back_to_local_images(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Registry timeout must not fail install when pin images are already local."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    site = "ghcr.io/zeegin/v8std-site:sha-test"
    mcp = "ghcr.io/zeegin/v8std-mcp:sha-test"

    def fake_run(cmd: list[str], **_kwargs: object) -> object:
        joined = " ".join(cmd)
        if cmd[:2] == ["docker", "compose"] and cmd[-1] == "pull":
            return type(
                "R",
                (),
                {
                    "returncode": 18,
                    "stdout": "",
                    "stderr": (
                        'Error response from daemon: Get "https://ghcr.io/v2/": '
                        "Client.Timeout exceeded while awaiting headers"
                    ),
                },
            )()
        if cmd[:2] == ["docker", "compose"] and "config" in cmd and "--images" in cmd:
            return type(
                "R",
                (),
                {"returncode": 0, "stdout": f"{site}\n{mcp}\n", "stderr": ""},
            )()
        if cmd[:3] == ["docker", "image", "inspect"]:
            return type("R", (), {"returncode": 0, "stdout": "[]", "stderr": ""})()
        raise AssertionError(f"unexpected subprocess: {joined}")

    with patch("core.tools.install.subprocess.run", side_effect=fake_run):
        result = install_tool("v8std", pull=True)
    assert result.status == "ok", result.diagnostics
    assert result.pulled is True
    assert any(
        d.get("severity") == "warning" and d.get("code") == "1CX006"
        for d in result.diagnostics
    )
    assert any("локальные образы" in (d.get("message") or "") for d in result.diagnostics)


def test_install_pull_fails_without_local_images(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    def fake_run(cmd: list[str], **_kwargs: object) -> object:
        if cmd[:2] == ["docker", "compose"] and cmd[-1] == "pull":
            return type(
                "R",
                (),
                {"returncode": 18, "stdout": "", "stderr": "timeout"},
            )()
        if cmd[:2] == ["docker", "compose"] and "config" in cmd and "--images" in cmd:
            return type(
                "R",
                (),
                {
                    "returncode": 0,
                    "stdout": "ghcr.io/zeegin/v8std-site:missing\n",
                    "stderr": "",
                },
            )()
        if cmd[:3] == ["docker", "image", "inspect"]:
            return type("R", (), {"returncode": 1, "stdout": "", "stderr": "No such"})()
        raise AssertionError(f"unexpected subprocess: {' '.join(cmd)}")

    with patch("core.tools.install.subprocess.run", side_effect=fake_run):
        result = install_tool("v8std", pull=True)
    assert result.status == "error"
    assert result.pulled is False
    assert any(
        d.get("severity") == "error" and d.get("code") == "1CX006"
        for d in result.diagnostics
    )


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
    result = configure_ide(project, target="all")
    assert result.status == "ok", result.diagnostics
    cursor = json.loads((project / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    assert "v8std" in cursor["mcpServers"]
    assert cursor["mcpServers"]["v8std"] == {
        "url": "http://127.0.0.1:18766/mcp",
    }
    assert "1c-dev" in cursor["mcpServers"]
    kilo = json.loads((project / ".kilo" / "mcp.json").read_text(encoding="utf-8"))
    assert kilo["mcpServers"]["v8std"] == {
        "type": "streamable-http",
        "url": "http://127.0.0.1:18766/mcp",
    }
    agents = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert "<!-- BEGIN 1c-dev:v8std -->" in agents
    assert "<!-- END 1c-dev:v8std -->" in agents
    rule = project / ".cursor" / "rules" / "ext-v8std-when-to-use.mdc"
    assert rule.is_file()
    assert "managedBy: 1c-dev" in rule.read_text(encoding="utf-8")


def test_ide_configure_upserts_kilocode_streamable_http_type(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Re-running configure adds type for managed HTTP servers in .kilo/mcp.json."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    install_tool("v8std", pull=False)
    project = tmp_path / "proj"
    project.mkdir()
    kilo_mcp = project / ".kilo" / "mcp.json"
    kilo_mcp.parent.mkdir(parents=True)
    kilo_mcp.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "1c-dev": {"command": "1c-dev", "args": ["mcp"]},
                    "v8std": {"url": "http://127.0.0.1:18766/mcp"},
                }
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    result = configure_ide(project, target="kilocode")
    assert result.status == "ok", result.diagnostics
    kilo = json.loads(kilo_mcp.read_text(encoding="utf-8"))
    assert kilo["mcpServers"]["v8std"] == {
        "type": "streamable-http",
        "url": "http://127.0.0.1:18766/mcp",
    }


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


def test_ide_configure_warns_unreachable_http_mcp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    install_tool("v8std", pull=False)
    project = tmp_path / "proj"
    project.mkdir()
    with patch(
        "core.services.health.check_http",
        return_value=HealthResult(
            url="http://127.0.0.1:18766/healthz",
            reachable=False,
            error="connection refused",
        ),
    ):
        result = configure_ide(project, target="cursor")
    assert result.status == "ok", result.diagnostics
    codes = {d.get("code") for d in result.diagnostics}
    assert "1CX005" in codes
    assert any(
        d.get("code") == "1CX005" and "services up v8std" in (d.get("suggestion") or "")
        for d in result.diagnostics
    )


def test_ide_configure_external_lifecycle_mcp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """lifecycle=external: MCP url без services / compose."""
    import yaml

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    tool_dir = tools_share_dir() / "ext-demo"
    tool_dir.mkdir(parents=True)
    (tool_dir / "tool.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "ext-demo",
                "name": "External demo",
                "version": "0.0.1",
                "mcp_name": "ext-demo",
                "scope": "user",
                "lifecycle": "external",
                "interface": {
                    "type": "mcp",
                    "transport": "streamable-http",
                    "url": "http://127.0.0.1:19999/mcp",
                },
                "agent": {"guidance": "agent/guidance.md"},
            }
        ),
        encoding="utf-8",
    )
    agent_dir = tool_dir / "agent"
    agent_dir.mkdir()
    (agent_dir / "guidance.md").write_text(
        "## Optional MCP: ext-demo\n\nWhen: demo.\n",
        encoding="utf-8",
    )
    project = tmp_path / "proj"
    project.mkdir()
    with patch(
        "core.services.health.check_http",
        return_value=HealthResult(url="x", reachable=True, status_code=200),
    ):
        result = configure_ide(project, target="cursor")
    assert result.status == "ok", result.diagnostics
    mcp = json.loads((project / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["ext-demo"] == {"url": "http://127.0.0.1:19999/mcp"}
    agents = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert "<!-- BEGIN 1c-dev:ext-demo -->" in agents


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


def test_cli_tools_install_all_no_pull(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    result = runner.invoke(
        app, ["tools", "install", "--all", "--no-pull", "--output", "json"]
    )
    assert result.exit_code == SUCCESS, result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["action"] == "install-all"
    ids = {r["toolId"] for r in payload["results"]}
    catalog_ids = set(list_catalog())
    assert ids == catalog_ids
    for tool_id in catalog_ids:
        assert is_installed(tool_id)


def test_cli_tools_install_id_xor_all(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    neither = runner.invoke(app, ["tools", "install", "--output", "json"])
    assert neither.exit_code == RUNTIME_FAILURE
    both = runner.invoke(
        app, ["tools", "install", "v8std", "--all", "--output", "json"]
    )
    assert both.exit_code == RUNTIME_FAILURE


def test_cli_services_list_after_install(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    install_tool("v8std", pull=False)
    from core.services.manager import ServiceResult
    from core.services.state import StackState, default_stack_labels, save_stack

    save_stack(
        StackState(
            tool_id="v8std",
            project_name="1c-dev-v8std",
            last_action="up",
            last_status="ok",
            healthy=True,
            running=True,
            mcp_url="http://127.0.0.1:18766/mcp",
            labels=default_stack_labels("v8std"),
        )
    )

    def fake_status(tool_id: str) -> ServiceResult:
        if tool_id == "v8std":
            return ServiceResult(
                tool_id=tool_id,
                status="ok",
                action="status",
                running=True,
                healthy=True,
                mcp_url="http://127.0.0.1:18766/mcp",
            )
        return ServiceResult(
            tool_id=tool_id,
            status="degraded",
            action="status",
            running=False,
            healthy=False,
        )

    with patch("core.services.manager.service_status", side_effect=fake_status):
        result = runner.invoke(app, ["services", "list", "--output", "json"])
    assert result.exit_code == SUCCESS, result.stdout
    payload = json.loads(result.stdout)
    by_id = {s["id"]: s for s in payload["services"]}
    assert "v8std" in by_id
    assert by_id["v8std"]["installed"] is True
    assert by_id["v8std"]["running"] is True
    assert by_id["v8std"]["healthy"] is True
    assert "bsl-ls" in by_id
    assert by_id["bsl-ls"]["installed"] is False


def test_cli_services_list_ignores_stale_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """After reboot state.json may say running; list must probe live."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    install_tool("v8std", pull=False)
    from core.services.state import StackState, default_stack_labels, save_stack

    save_stack(
        StackState(
            tool_id="v8std",
            project_name="1c-dev-v8std",
            last_action="up",
            last_status="ok",
            healthy=True,
            running=True,
            mcp_url="http://127.0.0.1:18766/mcp",
            labels=default_stack_labels("v8std"),
        )
    )
    with patch(
        "core.services.manager.check_http",
        return_value=HealthResult(
            url="http://127.0.0.1:18766/healthz",
            reachable=False,
            status_code=None,
        ),
    ):
        result = runner.invoke(app, ["services", "list", "--output", "json"])
    assert result.exit_code == SUCCESS, result.stdout
    payload = json.loads(result.stdout)
    by_id = {s["id"]: s for s in payload["services"]}
    assert by_id["v8std"]["running"] is False
    assert by_id["v8std"]["healthy"] is False
    # list reconciles state.json via service_status
    assert load_state()["v8std"].running is False
    assert load_state()["v8std"].healthy is False


def test_cli_services_up_all_skips_not_installed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from core.services.manager import ServiceResult

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    install_tool("bsl-ls", pull=False)
    jar = tools_share_dir() / "bsl-ls" / "lib" / "bsl-language-server.jar"
    jar.parent.mkdir(parents=True, exist_ok=True)
    jar.write_bytes(b"pk\x03\x04")

    def fake_up(tool_id: str, **_kwargs: object) -> ServiceResult:
        return ServiceResult(
            tool_id=tool_id,
            status="ok",
            action="up",
            running=True,
            healthy=True,
        )

    with patch("core.services.manager.service_up", side_effect=fake_up):
        result = runner.invoke(app, ["services", "up", "--all", "--output", "json"])
    assert result.exit_code == SUCCESS, result.stdout
    payload = json.loads(result.stdout)
    assert payload["action"] == "up-all"
    assert payload["status"] == "ok"
    by_id = {r["toolId"]: r for r in payload["results"]}
    assert by_id["bsl-ls"]["status"] == "ok"
    assert by_id["v8std"]["status"] == "ok"
    assert any(
        d.get("code") == "1CX002" for d in by_id["v8std"]["diagnostics"]
    )


def test_bulk_install_aggregate_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from core.tools.install import InstallResult, install_all_tools

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    def fake_install(tool_id: str, **_kwargs: object) -> InstallResult:
        if tool_id == "v8std":
            return InstallResult(tool_id=tool_id, status="error", diagnostics=[])
        return InstallResult(tool_id=tool_id, status="ok", path="/tmp", pulled=False)

    with patch("core.tools.install.install_tool", side_effect=fake_install):
        bulk = install_all_tools(pull=False)
    assert bulk.status == "error"
    assert any(r.tool_id == "v8std" and r.status == "error" for r in bulk.results)


def test_cli_services_id_xor_all() -> None:
    neither = runner.invoke(app, ["services", "up", "--output", "json"])
    assert neither.exit_code == RUNTIME_FAILURE
    both = runner.invoke(
        app, ["services", "up", "v8std", "--all", "--output", "json"]
    )
    assert both.exit_code == RUNTIME_FAILURE
