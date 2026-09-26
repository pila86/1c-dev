"""MCP tools: thin wrappers over core API (ADR-010 / #26 / #29)."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from adapters.source.xmlgen import EditOp, edit_op_from_dict
from core.build import run_build
from core.check import run_check
from core.docs import get_docs, search_docs
from core.import_cf import run_import
from core.metadata import (
    IrError,
    MetadataResult,
    catalog_from_json,
    create_metadata,
    delete_metadata,
    find_metadata,
    get_metadata,
    list_metadata,
    update_metadata,
)
from core.project import configure_ide, init_project, validate_project
from mcp_server._path import resolve_path

_NO_SHELL = (
    " Do not use shell, Designer/Configurator, or raw ibcmd for this operation — use this tool."
)


def _parse_update_operations(
    operations: list[dict[str, Any]] | None,
) -> list[EditOp] | MetadataResult:
    """Parse MCP operations[] into EditOp list, or return an error result."""
    if not operations:
        return MetadataResult(
            status="error",
            diagnostics=[
                {
                    "severity": "error",
                    "code": "1CM002",
                    "message": "Список операций пуст",
                    "source": "metadata",
                }
            ],
        )
    result: list[EditOp] = []
    for item in operations:
        if not isinstance(item, dict):
            return MetadataResult(
                status="error",
                diagnostics=[
                    {
                        "severity": "error",
                        "code": "1CM002",
                        "message": "Элемент operations должен быть объектом {op, value}",
                        "source": "metadata",
                    }
                ],
            )
        try:
            result.append(edit_op_from_dict(item))
        except ValueError as exc:
            return MetadataResult(
                status="error",
                diagnostics=[
                    {
                        "severity": "error",
                        "code": "1CM002",
                        "message": str(exc),
                        "source": "metadata",
                    }
                ],
            )
    return result


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
        name="ide.configure",
        description=(
            "Configure IDE MCP configs (cursor/kilocode), AGENTS.md, and .gitignore "
            "for an existing 1C project. "
            "target: all (default), cursor, kilocode, or none. "
            "Without force, does not overwrite AGENTS.md; merges missing MCP servers "
            "and .gitignore lines."
            + _NO_SHELL
        ),
    )
    def ide_configure_tool(
        path: str | None = None,
        target: str = "all",
        force: bool = False,
    ) -> dict[str, Any]:
        result = configure_ide(
            resolve_path(path),
            target=target,
            force=force,
        )
        return result.to_payload(include_manifest=False)

    @server.tool(
        name="project.import",
        description=(
            "Import a .cf configuration into project XML source via ibcmd "
            "(load → apply → export). Creates 1c.project.yaml if missing. "
            "Refuses to overwrite existing Configuration.xml unless force=true. "
            "Does not write AGENTS.md or IDE MCP configs (use ide.configure for that)."
            + _NO_SHELL
        ),
    )
    def project_import_tool(
        from_path: str,
        path: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        result = run_import(
            resolve_path(path),
            from_path=from_path,
            force=force,
        )
        return result.to_payload()

    @server.tool(
        name="metadata.list",
        description=(
            "List metadata objects in project XML source as IR summaries "
            "({type, name, qname, synonym?}). Use to survey the configuration "
            "before get/update/create/delete. Works from source without the 1C platform."
            + _NO_SHELL
        ),
    )
    def metadata_list(path: str | None = None) -> dict[str, Any]:
        result = list_metadata(resolve_path(path))
        return result.to_payload()

    @server.tool(
        name="metadata.get",
        description=(
            "Get full Metadata IR for one object by qualified name "
            "(e.g. Catalog.Products). Call before metadata.update to inspect "
            "existing attributes/tabular sections/values. Works from source "
            "without the 1C platform."
            + _NO_SHELL
        ),
    )
    def metadata_get(
        qualified_name: str,
        path: str | None = None,
    ) -> dict[str, Any]:
        result = get_metadata(resolve_path(path), qualified_name)
        return result.to_payload()

    @server.tool(
        name="metadata.find",
        description=(
            "Find metadata objects by substring of name or synonym. "
            "Returns IR summaries like metadata.list. Prefer over list when "
            "looking for a specific object."
            + _NO_SHELL
        ),
    )
    def metadata_find(
        query: str,
        path: str | None = None,
    ) -> dict[str, Any]:
        result = find_metadata(resolve_path(path), query)
        return result.to_payload()

    @server.tool(
        name="metadata.create",
        description=(
            "Create a new metadata object in XML source (does not modify existing "
            "objects — use metadata.update for that). "
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
        name="metadata.update",
        description=(
            "Apply edit operations to an existing metadata object. Prefer "
            "metadata.get first. Pass operations as [{op, value}, …]: "
            "add-attribute / modify-attribute / remove-attribute; "
            "add-ts / modify-ts / remove-ts; add-ts-attribute / remove-ts-attribute; "
            "add-enumValue / modify-enumValue / remove-enumValue; "
            "add-dimension / modify-dimension / remove-dimension; "
            "add-resource / modify-resource / remove-resource; "
            "modify-property; set-flag (CommonModule sugar → modify-property). "
            "Examples: {op:'add-attribute', value:'Price:Number(15,2)'}, "
            "{op:'modify-attribute', value:'Price: synonym=Цена'}, "
            "{op:'set-flag', value:'server=true'}. "
            "Does not create new objects — use metadata.create."
            + _NO_SHELL
        ),
    )
    def metadata_update(
        qualified_name: str,
        operations: list[dict[str, Any]] | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        parsed = _parse_update_operations(operations)
        if isinstance(parsed, MetadataResult):
            parsed.object = qualified_name
            return parsed.to_payload()
        result = update_metadata(resolve_path(path), qualified_name, parsed)
        return result.to_payload()

    @server.tool(
        name="metadata.delete",
        description=(
            "Delete a whole metadata object from XML source by qualified name "
            "(e.g. Catalog.Products). Removes object artifacts and Configuration.xml "
            "registration. Does not cascade references. Prefer metadata.get first. "
            "To remove attributes/tabular sections/values use metadata.update "
            "remove-* ops instead."
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

    @server.tool(
        name="docs.search",
        description=(
            "Search the local platform syntax-help index (bsl-context) for the "
            "project's platform.version. Builds the index lazily on first use. "
            "Returns hits with name/kind/snippet. Prefer over guessing API names."
            + _NO_SHELL
        ),
    )
    def docs_search_tool(
        query: str,
        path: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        result = search_docs(resolve_path(path), query, limit=limit)
        return result.to_payload()

    @server.tool(
        name="docs.get",
        description=(
            "Get a full syntax-help entry by name or Owner.Member "
            "(e.g. Массив, Массив.Добавить). Uses the project's platform.version "
            "index; builds it lazily on first use."
            + _NO_SHELL
        ),
    )
    def docs_get_tool(
        name: str,
        path: str | None = None,
    ) -> dict[str, Any]:
        result = get_docs(resolve_path(path), name)
        return result.to_payload()
