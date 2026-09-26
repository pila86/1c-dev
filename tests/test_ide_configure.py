"""Tests for ide configure (ADR-016 / #50)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from cli.main import app
from core.exit_codes import SUCCESS
from core.project import configure_ide
from core.project.ide import build_mcp_servers_payload, ides_to_configure, mcp_rel_path
from mcp_server import create_server

runner = CliRunner()


def test_ides_to_configure() -> None:
    assert ides_to_configure("all") == ["cursor", "kilocode"]
    assert ides_to_configure("cursor") == ["cursor"]
    assert ides_to_configure("kilocode") == ["kilocode"]
    assert ides_to_configure("none") == []
    with pytest.raises(ValueError):
        ides_to_configure("vscode")


def test_configure_default_all(tmp_path: Path) -> None:
    result = configure_ide(tmp_path)
    assert result.status == "ok"
    assert (tmp_path / "1c.project.yaml").is_file()
    assert (tmp_path / "AGENTS.md").is_file()
    assert (tmp_path / ".gitignore").is_file()
    assert (tmp_path / ".cursor" / "mcp.json").is_file()
    assert (tmp_path / ".kilo" / "mcp.json").is_file()
    assert "AGENTS.md" in result.created
    assert ".cursor/mcp.json" in result.created
    assert ".kilo/mcp.json" in result.created

    cursor = json.loads((tmp_path / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    servers = cursor["mcpServers"]
    assert set(servers) == {"1c-dev", "bsl-language-server"}
    assert servers["1c-dev"] == {"command": "1c-dev", "args": ["mcp"]}
    assert "cwd" not in servers["1c-dev"]
    bsl_args = servers["bsl-language-server"]["args"]
    assert bsl_args[0] == "-jar"
    assert bsl_args[2] == "mcp"
    assert Path(bsl_args[1]).is_absolute()


def test_configure_target_none(tmp_path: Path) -> None:
    result = configure_ide(tmp_path, target="none")
    assert result.status == "ok"
    assert (tmp_path / "AGENTS.md").is_file()
    assert (tmp_path / ".gitignore").is_file()
    assert not (tmp_path / ".cursor").exists()
    assert not (tmp_path / ".kilo").exists()


def test_configure_target_cursor_only(tmp_path: Path) -> None:
    result = configure_ide(tmp_path, target="cursor")
    assert result.status == "ok"
    assert (tmp_path / ".cursor" / "mcp.json").is_file()
    assert not (tmp_path / ".kilo").exists()
    assert mcp_rel_path("cursor") == ".cursor/mcp.json"


def test_configure_target_kilocode_only(tmp_path: Path) -> None:
    result = configure_ide(tmp_path, target="kilocode")
    assert result.status == "ok"
    assert (tmp_path / ".kilo" / "mcp.json").is_file()
    assert not (tmp_path / ".cursor").exists()


def test_configure_unknown_target(tmp_path: Path) -> None:
    result = configure_ide(tmp_path, target="vscode")
    assert result.status == "error"
    assert any(d.get("code") == "1CP007" for d in result.diagnostics)


def test_configure_repeat_preserves_agents_and_merges(
    tmp_path: Path,
) -> None:
    first = configure_ide(tmp_path, target="cursor")
    assert first.status == "ok"
    agents_text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text(agents_text + "\n# custom\n", encoding="utf-8")

    gi = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    (tmp_path / ".gitignore").write_text(gi + "custom_dir/\n", encoding="utf-8")
    lines = [
        line
        for line in (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() != ".cache/"
    ]
    (tmp_path / ".gitignore").write_text("\n".join(lines) + "\n", encoding="utf-8")

    mcp_path = tmp_path / ".cursor" / "mcp.json"
    data = json.loads(mcp_path.read_text(encoding="utf-8"))
    data["mcpServers"]["other"] = {"command": "echo"}
    del data["mcpServers"]["bsl-language-server"]
    mcp_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    second = configure_ide(tmp_path, target="cursor")
    assert second.status == "ok"
    assert "AGENTS.md" in second.skipped
    assert any(d.get("code") == "1CP008" for d in second.diagnostics)
    assert "# custom" in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")

    gi2 = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "custom_dir/" in gi2
    assert ".cache/" in gi2
    assert ".gitignore" in second.updated

    merged = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert "other" in merged["mcpServers"]
    assert "1c-dev" in merged["mcpServers"]
    assert "bsl-language-server" in merged["mcpServers"]
    assert merged["mcpServers"]["1c-dev"] == data["mcpServers"]["1c-dev"]
    assert ".cursor/mcp.json" in second.updated


def test_configure_force_overwrites_agents_and_mcp(tmp_path: Path) -> None:
    configure_ide(tmp_path, target="cursor")
    (tmp_path / "AGENTS.md").write_text("# user\n", encoding="utf-8")
    mcp_path = tmp_path / ".cursor" / "mcp.json"
    mcp_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "other": {"command": "echo"},
                    "1c-dev": {"command": "old"},
                }
            }
        ),
        encoding="utf-8",
    )

    result = configure_ide(tmp_path, target="cursor", force=True)
    assert result.status == "ok"
    agents = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "# user" not in agents
    assert "1C Development Rules" in agents
    assert "AGENTS.md" in result.updated

    data = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert set(data["mcpServers"]) == {"1c-dev", "bsl-language-server"}
    assert data["mcpServers"]["1c-dev"]["command"] == "1c-dev"


def test_configure_does_not_overwrite_existing_manifest_fields(tmp_path: Path) -> None:
    (tmp_path / "1c.project.yaml").write_text(
        'schema: "1"\n'
        "project:\n"
        "  name: Existing\n"
        "  type: configuration\n"
        "platform:\n"
        '  version: "8.3.25"\n'
        "source:\n"
        "  format: xml\n"
        "  path: src/cf\n"
        "runtime:\n"
        "  type: file\n"
        "  path: .runtime/ib\n",
        encoding="utf-8",
    )
    result = configure_ide(tmp_path, target="none")
    assert result.status == "ok"
    text = (tmp_path / "1c.project.yaml").read_text(encoding="utf-8")
    assert "Existing" in text
    assert "8.3.25" in text
    assert "1c.project.yaml" not in result.created


def test_build_mcp_servers_payload_no_cwd() -> None:
    payload = build_mcp_servers_payload(
        jar_path=Path("/tmp/bsl-language-server.jar"),
        java_command="java",
    )
    assert "cwd" not in payload["1c-dev"]
    assert payload["bsl-language-server"]["args"] == [
        "-jar",
        "/tmp/bsl-language-server.jar",
        "mcp",
    ]


def test_cli_ide_configure_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["ide", "configure", "--output", "json"])
    assert result.exit_code == SUCCESS, result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert (tmp_path / ".cursor" / "mcp.json").is_file()
    assert (tmp_path / ".kilo" / "mcp.json").is_file()


def test_cli_ide_configure_target_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app, ["ide", "configure", "--target", "none", "--output", "json"]
    )
    assert result.exit_code == SUCCESS, result.stdout
    assert not (tmp_path / ".cursor").exists()


def test_cli_project_ide_configure_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        ["--output", "json", "project", "ide", "configure", "--target", "cursor"],
    )
    assert result.exit_code == SUCCESS, result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert (tmp_path / ".cursor" / "mcp.json").is_file()


def test_cli_ide_configure_unknown_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app, ["ide", "configure", "--target", "vscode", "--output", "json"]
    )
    assert result.exit_code != SUCCESS


def _call(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    server = create_server()

    async def _run() -> dict[str, Any]:
        result = await server.call_tool(name, arguments or {})
        if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], dict):
            return result[1]
        raise AssertionError(f"Unexpected call_tool result: {result!r}")

    return asyncio.run(_run())


def test_mcp_ide_configure(tmp_path: Path) -> None:
    payload = _call(
        "ide.configure",
        {"path": str(tmp_path), "target": "cursor"},
    )
    assert payload["status"] == "ok"
    assert (tmp_path / ".cursor" / "mcp.json").is_file()
    assert not (tmp_path / ".kilo").exists()
