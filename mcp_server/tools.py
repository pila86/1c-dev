"""M1 MCP tools: thin wrappers over core API (ADR-010)."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from core.build import run_build
from core.check import run_check
from core.metadata import IrError, MetadataResult, catalog_from_json, create_metadata
from core.project import init_project, validate_project
from mcp_server._path import resolve_path

_NO_SHELL = (
    " Do not use shell, Designer/Configurator, or raw ibcmd for this operation — use this tool."
)


def register_tools(server: FastMCP) -> None:
    """Register M1 agent-facing tools on the given FastMCP server."""

    @server.tool(
        name="project.get",
        description=(
            "Read and validate the 1C project (1c.project.yaml) and return structured JSON "
            "including the full manifest." + _NO_SHELL
        ),
    )
    def project_get(path: str | None = None) -> dict[str, Any]:
        result = validate_project(resolve_path(path))
        return result.to_payload(include_manifest=True)

    @server.tool(
        name="project.init",
        description=(
            "Bootstrap an empty 1C configuration project (1c.project.yaml + XML source skeleton)."
            + _NO_SHELL
        ),
    )
    def project_init(
        path: str | None = None,
        type: str = "configuration",
        name: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        result = init_project(
            resolve_path(path),
            project_type=type,
            name=name,
            force=force,
        )
        return result.to_payload(include_manifest=False)

    @server.tool(
        name="metadata.create",
        description=(
            "Create a metadata object in XML source (M1: Catalog only). "
            "Pass qualified_name like Catalog.Products and optional structured attributes."
            + _NO_SHELL
        ),
    )
    def metadata_create(
        qualified_name: str,
        synonym: str | None = None,
        attributes: list[dict[str, Any]] | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        try:
            data: dict[str, Any] = {"type": "Catalog", "attributes": list(attributes or [])}
            if synonym:
                data["synonym"] = synonym
            catalog = catalog_from_json(data, qualified_name=qualified_name)
            if synonym and not catalog.synonym:
                catalog.synonym = synonym
        except IrError as exc:
            return MetadataResult(
                status="error",
                diagnostics=[
                    {
                        "severity": "error",
                        "code": exc.code,
                        "message": exc.message,
                        "source": "metadata",
                    }
                ],
            ).to_payload()
        result = create_metadata(resolve_path(path), catalog)
        return result.to_payload()

    @server.tool(
        name="build",
        description=(
            "Load XML configuration into a file infobase via ibcmd. "
            "Optional artifact='cf' exports a .cf file." + _NO_SHELL
        ),
    )
    def build_tool(
        path: str | None = None,
        artifact: str | None = None,
    ) -> dict[str, Any]:
        result = run_build(resolve_path(path), artifact=artifact)
        return result.to_payload()

    @server.tool(
        name="check",
        description=(
            "Run platform configuration check (ibcmd config check) on an existing file IB. "
            "Requires a prior successful build." + _NO_SHELL
        ),
    )
    def check_tool(path: str | None = None) -> dict[str, Any]:
        result = run_check(resolve_path(path))
        return result.to_payload()
