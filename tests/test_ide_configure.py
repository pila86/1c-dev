"""Tests for ide configure (ADR-016 / #50 / #90)."""

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
from core.project.ide import (
    AGENTS_BEGIN,
    AGENTS_END,
    RULES_MD_MARKER,
    _load_rules_pack,
    build_mcp_servers_payload,
    ides_to_configure,
    mcp_rel_path,
    render_cursor_rule,
    render_kilocode_rule,
    rule_file_rel,
)
from mcp_server import create_server

runner = CliRunner()

RULE_IDS = (
    "bsl-string-literals",
    "bsl-module-structure",
    "1c-service-addresses",
    "bsl-transactions",
)


def _assert_rules_present(root: Path, *ides: str) -> None:
    pack = {spec.id: spec for spec in _load_rules_pack()}
    for ide in ides:
        for rule_id in RULE_IDS:
            path = root / rule_file_rel(ide, rule_id)  # type: ignore[arg-type]
            assert path.is_file(), path
            text = path.read_text(encoding="utf-8")
            if ide == "cursor":
                assert "managedBy: 1c-dev" in text
                assert text == render_cursor_rule(pack[rule_id])
            else:
                assert text.startswith(RULES_MD_MARKER)
                assert text == render_kilocode_rule(pack[rule_id])


def _assert_rules_absent(root: Path, *ides: str) -> None:
    for ide in ides:
        for rule_id in RULE_IDS:
            assert not (root / rule_file_rel(ide, rule_id)).exists()  # type: ignore[arg-type]


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
    assert result.ide_root == tmp_path.resolve()
    assert (tmp_path / ".1c-dev" / "project.yaml").is_file()
    assert (tmp_path / "AGENTS.md").is_file()
    agents = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert AGENTS_BEGIN in agents
    assert AGENTS_END in agents
    assert (tmp_path / ".gitignore").is_file()
    assert (tmp_path / ".cursor" / "mcp.json").is_file()
    assert (tmp_path / ".kilo" / "mcp.json").is_file()
    assert "AGENTS.md" in result.created
    assert ".cursor/mcp.json" in result.created
    assert ".kilo/mcp.json" in result.created
    _assert_rules_present(tmp_path, "cursor", "kilocode")
    for rule_id in RULE_IDS:
        assert f".cursor/rules/{rule_id}.mdc" in result.created
        assert f".kilo/rules/{rule_id}.md" in result.created

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
    _assert_rules_absent(tmp_path, "cursor", "kilocode")


def test_configure_target_cursor_only(tmp_path: Path) -> None:
    result = configure_ide(tmp_path, target="cursor")
    assert result.status == "ok"
    assert (tmp_path / ".cursor" / "mcp.json").is_file()
    assert not (tmp_path / ".kilo").exists()
    assert mcp_rel_path("cursor") == ".cursor/mcp.json"
    _assert_rules_present(tmp_path, "cursor")
    _assert_rules_absent(tmp_path, "kilocode")


def test_configure_target_kilocode_only(tmp_path: Path) -> None:
    result = configure_ide(tmp_path, target="kilocode")
    assert result.status == "ok"
    assert (tmp_path / ".kilo" / "mcp.json").is_file()
    assert not (tmp_path / ".cursor").exists()
    _assert_rules_present(tmp_path, "kilocode")
    _assert_rules_absent(tmp_path, "cursor")

def test_configure_unknown_target(tmp_path: Path) -> None:
    result = configure_ide(tmp_path, target="vscode")
    assert result.status == "error"
    assert any(d.get("code") == "1CP007" for d in result.diagnostics)


def test_configure_unknown_agents(tmp_path: Path) -> None:
    result = configure_ide(tmp_path, agents="everywhere")
    assert result.status == "error"
    assert any(d.get("code") == "1CP010" for d in result.diagnostics)


def test_configure_repeat_merges_agents_and_mcp(tmp_path: Path) -> None:
    first = configure_ide(tmp_path, target="cursor")
    assert first.status == "ok"
    agents_text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text(
        agents_text + "\n# custom outside block\n", encoding="utf-8"
    )

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
    assert not any(d.get("code") == "1CP008" for d in second.diagnostics)
    agents_after = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "# custom outside block" in agents_after
    assert AGENTS_BEGIN in agents_after

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


def test_configure_merges_agents_into_existing_foreign_file(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# Orchestrator rules\n\nKeep me.\n", encoding="utf-8")
    result = configure_ide(tmp_path, target="none")
    assert result.status == "ok"
    assert "AGENTS.md" in result.updated
    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "# Orchestrator rules" in text
    assert "Keep me." in text
    assert AGENTS_BEGIN in text
    assert AGENTS_END in text
    assert "# Правила 1c-dev" in text


def test_configure_updates_stale_agents_block(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text(
        f"{AGENTS_BEGIN}\n# stale\n{AGENTS_END}\n\n# user note\n",
        encoding="utf-8",
    )
    result = configure_ide(tmp_path, target="none")
    assert result.status == "ok"
    assert "AGENTS.md" in result.updated
    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "# stale" not in text
    assert "# Правила 1c-dev" in text
    assert "# user note" in text


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
    assert "# Правила 1c-dev" in agents
    assert AGENTS_BEGIN in agents
    assert "AGENTS.md" in result.updated

    data = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert set(data["mcpServers"]) == {"1c-dev", "bsl-language-server"}
    assert data["mcpServers"]["1c-dev"]["command"] == "1c-dev"


def test_configure_agents_none_skips_agents(tmp_path: Path) -> None:
    result = configure_ide(tmp_path, target="none", agents="none")
    assert result.status == "ok"
    assert not (tmp_path / "AGENTS.md").exists()
    assert (tmp_path / ".gitignore").is_file()


def test_configure_ide_root_differs_auto_skips_scope_agents(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    scope = repo / "products" / "shop"
    scope.mkdir(parents=True)
    (repo / "AGENTS.md").write_text("# root orchestrator\n", encoding="utf-8")

    result = configure_ide(
        scope,
        ide_root=repo,
        target="cursor",
        agents="auto",
    )
    assert result.status == "ok"
    assert result.ide_root == repo.resolve()
    assert (scope / ".1c-dev" / "project.yaml").is_file()
    assert (scope / ".gitignore").is_file()
    assert not (scope / "AGENTS.md").exists()
    assert (repo / ".cursor" / "mcp.json").is_file()
    assert not (scope / ".cursor").exists()
    assert (repo / "AGENTS.md").read_text(encoding="utf-8") == "# root orchestrator\n"
    _assert_rules_present(repo, "cursor")
    _assert_rules_absent(scope, "cursor")


def test_configure_ide_root_differs_agents_scope(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    scope = repo / "products" / "shop"
    scope.mkdir(parents=True)
    (repo / "AGENTS.md").write_text("# root orchestrator\n", encoding="utf-8")

    result = configure_ide(
        scope,
        ide_root=repo,
        target="cursor",
        agents="scope",
        force=True,
    )
    assert result.status == "ok"
    assert (scope / "AGENTS.md").is_file()
    assert AGENTS_BEGIN in (scope / "AGENTS.md").read_text(encoding="utf-8")
    assert (repo / "AGENTS.md").read_text(encoding="utf-8") == "# root orchestrator\n"
    assert (repo / ".cursor" / "mcp.json").is_file()


def test_configure_does_not_overwrite_existing_manifest_fields(tmp_path: Path) -> None:
    home = tmp_path / ".1c-dev"
    home.mkdir()
    (home / "project.yaml").write_text(
        'schema: "2"\n'
        "project:\n"
        "  name: Existing\n"
        "  type: configuration\n"
        "platform:\n"
        '  version: "8.3.25"\n'
        "configurations:\n"
        "  - id: main\n"
        "    type: configuration\n"
        "    default: true\n"
        "    source:\n"
        "      format: xml\n"
        "      path: src/cf\n"
        "runtimes:\n"
        "  - id: main\n"
        "    configuration: main\n"
        "    type: file\n"
        "    path: .1c-dev/runtime/main\n"
        "    default: true\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "cf").mkdir(parents=True)
    result = configure_ide(tmp_path, target="none")
    assert result.status == "ok"
    text = (home / "project.yaml").read_text(encoding="utf-8")
    assert "Existing" in text
    assert "8.3.25" in text
    assert ".1c-dev/project.yaml" not in result.created


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
    assert payload["ide_root"] == str(tmp_path.resolve())
    assert (tmp_path / ".cursor" / "mcp.json").is_file()
    assert (tmp_path / ".kilo" / "mcp.json").is_file()


def test_cli_ide_configure_project_and_ide_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    scope = repo / "shop"
    scope.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        [
            "ide",
            "configure",
            "--project",
            str(scope),
            "--ide-root",
            str(repo),
            "--agents",
            "scope",
            "--target",
            "cursor",
            "--output",
            "json",
        ],
    )
    assert result.exit_code == SUCCESS, result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["ide_root"] == str(repo.resolve())
    assert (repo / ".cursor" / "mcp.json").is_file()
    assert (scope / "AGENTS.md").is_file()
    assert not (scope / ".cursor").exists()


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


def test_mcp_ide_configure_ide_root_and_agents(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    scope = repo / "shop"
    scope.mkdir(parents=True)
    (repo / "AGENTS.md").write_text("# keep\n", encoding="utf-8")
    payload = _call(
        "ide.configure",
        {
            "path": str(scope),
            "ide_root": str(repo),
            "target": "cursor",
            "agents": "auto",
        },
    )
    assert payload["status"] == "ok"
    assert payload["ide_root"] == str(repo.resolve())
    assert (repo / ".cursor" / "mcp.json").is_file()
    assert not (scope / "AGENTS.md").exists()
    assert (repo / "AGENTS.md").read_text(encoding="utf-8") == "# keep\n"


def test_configure_rules_repeat_skips_identical(tmp_path: Path) -> None:
    first = configure_ide(tmp_path, target="cursor")
    assert first.status == "ok"
    second = configure_ide(tmp_path, target="cursor")
    assert second.status == "ok"
    for rule_id in RULE_IDS:
        rel = f".cursor/rules/{rule_id}.mdc"
        assert rel in first.created
        assert rel in second.skipped
        assert rel not in second.created
        assert rel not in second.updated


def test_configure_rules_updates_managed_when_stale(tmp_path: Path) -> None:
    configure_ide(tmp_path, target="cursor")
    stale = tmp_path / ".cursor" / "rules" / "bsl-string-literals.mdc"
    stale.write_text(
        "---\n"
        "description: stale\n"
        "alwaysApply: true\n"
        "managedBy: 1c-dev\n"
        "---\n"
        "\n"
        "# stale body\n",
        encoding="utf-8",
    )
    result = configure_ide(tmp_path, target="cursor")
    assert result.status == "ok"
    assert ".cursor/rules/bsl-string-literals.mdc" in result.updated
    _assert_rules_present(tmp_path, "cursor")


def test_configure_rules_skips_foreign_same_name(tmp_path: Path) -> None:
    foreign = tmp_path / ".cursor" / "rules" / "bsl-string-literals.mdc"
    foreign.parent.mkdir(parents=True)
    foreign.write_text("# user custom rule\n", encoding="utf-8")
    result = configure_ide(tmp_path, target="cursor")
    assert result.status == "ok"
    assert ".cursor/rules/bsl-string-literals.mdc" in result.skipped
    assert any(d.get("code") == "1CP011" for d in result.diagnostics)
    assert foreign.read_text(encoding="utf-8") == "# user custom rule\n"
    assert (tmp_path / ".cursor" / "rules" / "bsl-module-structure.mdc").is_file()


def test_configure_rules_force_keeps_foreign_and_neighbor(tmp_path: Path) -> None:
    configure_ide(tmp_path, target="cursor")
    foreign_name = tmp_path / ".cursor" / "rules" / "git-commit.mdc"
    foreign_name.write_text("# neighbor\n", encoding="utf-8")
    colliding = tmp_path / ".cursor" / "rules" / "1c-service-addresses.mdc"
    colliding.write_text("# foreign collide\n", encoding="utf-8")

    result = configure_ide(tmp_path, target="cursor", force=True)
    assert result.status == "ok"
    assert foreign_name.read_text(encoding="utf-8") == "# neighbor\n"
    assert colliding.read_text(encoding="utf-8") == "# foreign collide\n"
    assert ".cursor/rules/1c-service-addresses.mdc" in result.skipped
    assert any(d.get("code") == "1CP011" for d in result.diagnostics)
    assert (tmp_path / ".cursor" / "rules" / "bsl-string-literals.mdc").is_file()


def test_mcp_ide_configure_writes_rules(tmp_path: Path) -> None:
    payload = _call(
        "ide.configure",
        {"path": str(tmp_path), "target": "all"},
    )
    assert payload["status"] == "ok"
    _assert_rules_present(tmp_path, "cursor", "kilocode")
