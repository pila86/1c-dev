"""Tests for MCP server (ADR-010, Issue #6)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from cli.main import app
from core.build import BuildResult
from core.check import CheckResult
from core.metadata import MetadataResult
from core.project import ProjectResult
from mcp_server import create_server
from mcp_server._path import resolve_path

runner = CliRunner()

EXPECTED_TOOLS = {
    "project.get",
    "project.init",
    "metadata.create",
    "metadata.delete",
    "build",
    "check",
}


def _call(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    server = create_server()

    async def _run() -> dict[str, Any]:
        result = await server.call_tool(name, arguments or {})
        # FastMCP returns (content_blocks, structured_dict) for dict-returning tools
        if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], dict):
            return result[1]
        raise AssertionError(f"Unexpected call_tool result: {result!r}")

    return asyncio.run(_run())


def test_resolve_path_defaults_to_cwd(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    assert resolve_path(None) == tmp_path.resolve()
    assert resolve_path("") == tmp_path.resolve()
    nested = tmp_path / "proj"
    nested.mkdir()
    assert resolve_path(str(nested)) == nested.resolve()


def test_registered_tools() -> None:
    server = create_server()
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert names == EXPECTED_TOOLS
    assert "shell.exec" not in names
    for tool in tools:
        assert "Do not use shell" in tool.description or "shell" in tool.description.lower()


def test_cli_mcp_help() -> None:
    result = runner.invoke(app, ["mcp", "--help"])
    assert result.exit_code == 0
    assert "stdio" in result.stdout.lower() or "MCP" in result.stdout or "mcp" in result.stdout


def test_project_get_and_init(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()

    missing = _call("project.get", {"path": str(target)})
    assert missing["status"] == "error"
    assert any(d.get("code") == "1CP001" for d in missing["diagnostics"])

    created = _call(
        "project.init",
        {"path": str(target), "type": "configuration", "name": "Shop"},
    )
    assert created["status"] == "ok"
    assert (target / "1c.project.yaml").is_file()

    info = _call("project.get", {"path": str(target)})
    assert info["status"] == "ok"
    assert "manifest" in info
    assert info["manifest"]["project"]["name"] == "Shop"


def test_metadata_create_ir_error() -> None:
    payload = _call(
        "metadata.create",
        {"qualified_name": "Document.Foo", "path": "/tmp"},
    )
    assert payload["status"] == "error"
    assert any(d.get("code") == "1CM002" for d in payload["diagnostics"])


def test_metadata_create_mocked(tmp_path: Path, monkeypatch: Any) -> None:
    target = tmp_path / "shop"
    target.mkdir()

    def fake_create(start: Path, catalog: Any, **kwargs: Any) -> MetadataResult:
        assert start == target.resolve()
        assert catalog.qualified_name == "Catalog.Products"
        assert catalog.synonym == "Товары"
        assert len(catalog.attributes) == 1
        assert catalog.attributes[0].name == "Article"
        return MetadataResult(
            status="ok",
            object="Catalog.Products",
            root=start,
            created=["src/cf/Catalogs/Products.xml"],
        )

    monkeypatch.setattr("mcp_server.tools.create_metadata", fake_create)
    payload = _call(
        "metadata.create",
        {
            "path": str(target),
            "qualified_name": "Catalog.Products",
            "synonym": "Товары",
            "attributes": [
                {"name": "Article", "type": "String", "length": 50, "synonym": "Артикул"}
            ],
        },
    )
    assert payload["status"] == "ok"
    assert payload["object"] == "Catalog.Products"


def test_metadata_delete_mocked(tmp_path: Path, monkeypatch: Any) -> None:
    target = tmp_path / "shop"
    target.mkdir()

    def fake_delete(start: Path, qualified_name: str, **kwargs: Any) -> MetadataResult:
        assert start == target.resolve()
        assert qualified_name == "Catalog.Products"
        return MetadataResult(
            status="ok",
            object="Catalog.Products",
            root=start,
            deleted=["src/cf/Catalogs/Products.xml"],
        )

    monkeypatch.setattr("mcp_server.tools.delete_metadata", fake_delete)
    payload = _call(
        "metadata.delete",
        {"path": str(target), "qualified_name": "Catalog.Products"},
    )
    assert payload["status"] == "ok"
    assert payload["object"] == "Catalog.Products"
    assert payload["deleted"] == ["src/cf/Catalogs/Products.xml"]


def test_build_and_check_mocked(tmp_path: Path, monkeypatch: Any) -> None:
    target = tmp_path / "shop"
    target.mkdir()

    def fake_build(start: Path, *, artifact: str | None = None, **kwargs: Any) -> BuildResult:
        assert start == target.resolve()
        assert artifact == "cf"
        return BuildResult(status="ok", root=start, steps=["import"], artifact="build/out/x.cf")

    def fake_check(start: Path, **kwargs: Any) -> CheckResult:
        assert start == target.resolve()
        return CheckResult(status="ok", root=start)

    monkeypatch.setattr("mcp_server.tools.run_build", fake_build)
    monkeypatch.setattr("mcp_server.tools.run_check", fake_check)

    build_payload = _call("build", {"path": str(target), "artifact": "cf"})
    assert build_payload["status"] == "ok"
    assert build_payload["artifact"] == "build/out/x.cf"

    check_payload = _call("check", {"path": str(target)})
    assert check_payload["status"] == "ok"


def test_project_init_mocked(tmp_path: Path, monkeypatch: Any) -> None:
    target = tmp_path / "x"
    target.mkdir()

    def fake_init(
        path: Path,
        *,
        project_type: str = "configuration",
        name: str | None = None,
        force: bool = False,
    ) -> ProjectResult:
        assert path == target.resolve()
        assert project_type == "configuration"
        assert name == "Demo"
        assert force is True
        return ProjectResult(status="ok", path=path / "1c.project.yaml", root=path, created=["a"])

    monkeypatch.setattr("mcp_server.tools.init_project", fake_init)
    payload = _call(
        "project.init",
        {"path": str(target), "type": "configuration", "name": "Demo", "force": True},
    )
    assert payload["status"] == "ok"
    assert payload["created"] == ["a"]
