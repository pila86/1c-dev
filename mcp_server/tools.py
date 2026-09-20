"""MCP tools: thin wrappers over core API (ADR-010 / #29)."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from core.build import run_build
from core.check import run_check
from core.metadata import (
    IrError,
    MetadataResult,
    catalog_from_json,
    create_metadata,
    delete_metadata,
)
from core.project import init_project, validate_project
from mcp_server._path import resolve_path

_NO_SHELL = (
    " Do not use shell, Designer/Configurator, or raw ibcmd for this operation — use this tool."
)


def register_tools(server: FastMCP) -> None:
    """Register agent-facing tools on the given FastMCP server."""

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
            "Create a metadata object in XML source. "
            "Types: Catalog, Document, Enum, InformationRegister, "
            "AccumulationRegister, CommonModule. Pass qualified_name "
            "(e.g. Catalog.Products, Enum.Statuses, CommonModule.SalesServer); "
            "optional synonym; "
            "for Catalog/Document: attributes and tabular_sections; "
            "for Enum: values [{name, synonym?}]; "
            "for registers: dimensions and resources (same shape as attributes); "
            "for CommonModule: optional flags server, client "
            "(→ clientManagedApplication), client_ordinary_application, "
            "server_call, external_connection, privileged, global, "
            "return_values_reuse (DontUse|DuringRequest|DuringSession). "
            "BSL body is not written (empty Module.bsl)."
            + _NO_SHELL
        ),
    )
    def metadata_create(
        qualified_name: str,
        synonym: str | None = None,
        attributes: list[dict[str, Any]] | None = None,
        tabular_sections: list[dict[str, Any]] | None = None,
        values: list[dict[str, Any]] | None = None,
        dimensions: list[dict[str, Any]] | None = None,
        resources: list[dict[str, Any]] | None = None,
        server: bool | None = None,
        client: bool | None = None,
        client_ordinary_application: bool | None = None,
        server_call: bool | None = None,
        external_connection: bool | None = None,
        privileged: bool | None = None,
        global_: bool | None = None,
        return_values_reuse: str | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        try:
            data: dict[str, Any] = {}
            if attributes:
                data["attributes"] = list(attributes)
            if synonym:
                data["synonym"] = synonym
            if tabular_sections:
                data["tabularSections"] = list(tabular_sections)
            if values:
                data["values"] = list(values)
            if dimensions:
                data["dimensions"] = list(dimensions)
            if resources:
                data["resources"] = list(resources)
            if server is not None:
                data["server"] = server
            if client is not None:
                data["client"] = client
            if client_ordinary_application is not None:
                data["clientOrdinaryApplication"] = client_ordinary_application
            if server_call is not None:
                data["serverCall"] = server_call
            if external_connection is not None:
                data["externalConnection"] = external_connection
            if privileged is not None:
                data["privileged"] = privileged
            if global_ is not None:
                data["global"] = global_
            if return_values_reuse is not None:
                data["returnValuesReuse"] = return_values_reuse
            # type/name come from qualified_name (validated inside catalog_from_json)
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
        name="metadata.delete",
        description=(
            "Delete a whole metadata object from XML source by qualified name "
            "(e.g. Catalog.Products). Removes object artifacts and Configuration.xml "
            "registration. Does not cascade references."
            + _NO_SHELL
        ),
    )
    def metadata_delete(
        qualified_name: str,
        path: str | None = None,
    ) -> dict[str, Any]:
        result = delete_metadata(resolve_path(path), qualified_name)
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
