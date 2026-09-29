"""MCP tools: thin wrappers over core API (ADR-010 / #26 / #29)."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from adapters.source.xmlgen import EditOp, edit_op_from_dict
from core.build import run_build
from core.check import run_check
from core.docs import get_docs, search_docs
from core.extension import add_extension, run_extension_list
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
from core.metadata.types import WRITE_OBJECT_TYPES_HELP
from core.project import (
    configure_ide,
    init_project,
    list_projects,
    run_clean,
    validate_project,
)
from core.runtime import run_start, run_status, run_stop
from mcp_server._path import resolve_path

_NO_SHELL = (
    " Do not use shell, Designer/Configurator, or raw ibcmd for this operation — use this tool."
)
_PATH_SCOPE = (
    " Argument path is the scope root (parent of .1c-dev), not the home directory itself."
)
_CONFIG_RUNTIME = (
    " Optional config_id / runtime_id select configurations[] / runtimes[] "
    "(defaults: configuration default:true or sole; runtime global default:true)."
)
_WRITE_TYPES = (
    "Write types (23 Meta DSL + Subsystem): " + WRITE_OBJECT_TYPES_HELP + "."
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
            "Read and validate the 1C project (.1c-dev/project.yaml or legacy "
            "1c.project.yaml) and return structured JSON including home, root, "
            "manifest_path, runtimes, and the full manifest."
            + _PATH_SCOPE
            + _NO_SHELL
        ),
    )
    def project_get(path: str | None = None) -> dict[str, Any]:
        result = validate_project(resolve_path(path))
        return result.to_payload(include_manifest=True)

    @server.tool(
        name="project.list",
        description=(
            "Scan downward from path for nested 1C projects (.1c-dev/project.yaml) "
            "with a limited depth (monorepo discovery). "
            "Returns a list of projects with root/home/manifest_path."
            + _PATH_SCOPE
            + _NO_SHELL
        ),
    )
    def project_list_tool(
        path: str | None = None,
        depth: int = 4,
    ) -> dict[str, Any]:
        results = list_projects(resolve_path(path), max_depth=depth)
        return {
            "status": "ok",
            "projects": [r.to_payload(include_manifest=False) for r in results],
        }

    @server.tool(
        name="project.init",
        description=(
            "Bootstrap an empty 1C project "
            "(.1c-dev/project.yaml schema 2 + XML source skeleton + IDE MCP configs). "
            "type: configuration (default) or extension (standalone). "
            "ide_target: all (default), cursor, kilocode, or none."
            + _PATH_SCOPE
            + _NO_SHELL
        ),
    )
    def project_init(
        path: str | None = None,
        type: str = "configuration",
        name: str | None = None,
        force: bool = False,
        ide_target: str = "all",
    ) -> dict[str, Any]:
        result = init_project(
            resolve_path(path),
            project_type=type,
            name=name,
            force=force,
            ide_target=ide_target,
        )
        return result.to_payload(include_manifest=False)

    @server.tool(
        name="extension.add",
        description=(
            "Add an extension to an existing configuration project: scaffold "
            "src/cfe/<id>/ and append configurations[].extensions[]. "
            "purpose: product (default), tests, or other."
            + _PATH_SCOPE
            + _CONFIG_RUNTIME
            + _NO_SHELL
        ),
    )
    def extension_add_tool(
        path: str | None = None,
        id: str | None = None,
        name: str | None = None,
        purpose: str = "product",
        config_id: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        result = add_extension(
            resolve_path(path),
            ext_id=id,
            name=name,
            purpose=purpose,
            config_id=config_id,
            force=force,
        )
        return result.to_payload(include_manifest=False)

    @server.tool(
        name="extension.list",
        description=(
            "List extensions installed in the selected/default file IB "
            "(ibcmd extension list)."
            + _PATH_SCOPE
            + _CONFIG_RUNTIME
            + _NO_SHELL
        ),
    )
    def extension_list_tool(
        path: str | None = None,
        config_id: str | None = None,
        runtime_id: str | None = None,
    ) -> dict[str, Any]:
        result = run_extension_list(
            resolve_path(path),
            config_id=config_id,
            runtime_id=runtime_id,
        )
        return result.to_payload()

    @server.tool(
        name="ide.configure",
        description=(
            "Configure IDE MCP configs (cursor/kilocode), AGENTS.md, and .gitignore "
            "for an existing 1C project. "
            "target: all (default), cursor, kilocode, or none. "
            "Without force, does not overwrite AGENTS.md; merges missing MCP servers "
            "and .gitignore lines."
            + _PATH_SCOPE
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
            "(load → apply → export). Creates .1c-dev/project.yaml (schema 2) if missing. "
            "Refuses to overwrite existing Configuration.xml unless force=true. "
            "Set break_support=true to strip ParentConfigurations* support "
            "artifacts after export (vendor update will no longer be possible). "
            "Does not write AGENTS.md or IDE MCP configs (use ide.configure for that)."
            + _PATH_SCOPE
            + _NO_SHELL
        ),
    )
    def project_import_tool(
        from_path: str,
        path: str | None = None,
        force: bool = False,
        break_support: bool = False,
    ) -> dict[str, Any]:
        result = run_import(
            resolve_path(path),
            from_path=from_path,
            force=force,
            break_support=break_support,
        )
        return result.to_payload()

    @server.tool(
        name="project.clean",
        description=(
            "DESTRUCTIVE: wipe project XML source (default configuration source.path) "
            "and the entire .1c-dev/runtime/ directory (file IB, ibcmd-data, client state). "
            "Also removes legacy .runtime/ if present. "
            "Requires yes=true. Does not touch .1c-dev/project.yaml, AGENTS.md, IDE MCP "
            "configs, .gitignore, or git. Stops a live runtime client first. "
            "Idempotent if already empty. Typical follow-up: project.import or init."
            " Optional config_id/runtime_id wipe only that source/runtime; "
            "without them wipe default source and entire .1c-dev/runtime/."
            + _PATH_SCOPE
            + _NO_SHELL
        ),
    )
    def project_clean_tool(
        yes: bool = False,
        path: str | None = None,
        config_id: str | None = None,
        runtime_id: str | None = None,
    ) -> dict[str, Any]:
        result = run_clean(
            resolve_path(path),
            yes=yes,
            config_id=config_id,
            runtime_id=runtime_id,
        )
        return result.to_payload()

    @server.tool(
        name="metadata.list",
        description=(
            "List metadata objects in project XML source as IR summaries "
            "({type, name, qname, synonym?}). Use to survey the configuration "
            "before get/update/create/delete. Works from source without the 1C platform."
            + _CONFIG_RUNTIME
            + _PATH_SCOPE
            + _NO_SHELL
        ),
    )
    def metadata_list(
        path: str | None = None,
        config_id: str | None = None,
        runtime_id: str | None = None,
    ) -> dict[str, Any]:
        result = list_metadata(
            resolve_path(path),
            config_id=config_id,
            runtime_id=runtime_id,
        )
        return result.to_payload()

    @server.tool(
        name="metadata.get",
        description=(
            "Get full Metadata IR for one object by qualified name "
            "(e.g. Catalog.Products). Call before metadata.update to inspect "
            "existing attributes/tabular sections/values. Works from source "
            "without the 1C platform."
            + _CONFIG_RUNTIME
            + _NO_SHELL
        ),
    )
    def metadata_get(
        qualified_name: str,
        path: str | None = None,
        config_id: str | None = None,
        runtime_id: str | None = None,
    ) -> dict[str, Any]:
        result = get_metadata(
            resolve_path(path),
            qualified_name,
            config_id=config_id,
            runtime_id=runtime_id,
        )
        return result.to_payload()

    @server.tool(
        name="metadata.find",
        description=(
            "Find metadata objects by substring of name or synonym. "
            "Returns IR summaries like metadata.list. Prefer over list when "
            "looking for a specific object."
            + _CONFIG_RUNTIME
            + _NO_SHELL
        ),
    )
    def metadata_find(
        query: str,
        path: str | None = None,
        config_id: str | None = None,
        runtime_id: str | None = None,
    ) -> dict[str, Any]:
        result = find_metadata(
            resolve_path(path),
            query,
            config_id=config_id,
            runtime_id=runtime_id,
        )
        return result.to_payload()

    @server.tool(
        name="metadata.create",
        description=(
            "Create a new metadata object in XML source (does not modify existing "
            "objects — use metadata.update for that). "
            + _WRITE_TYPES
            + " Pass qualified_name "
            "(e.g. Catalog.Products, Enum.Statuses, CommonModule.SalesServer, "
            "Subsystem.Main, Constant.VATRate, DefinedType.CounterpartyRef, "
            "Report.Sales, DataProcessor.ImportData, ScheduledJob.Cleanup, "
            "EventSubscription.ProductsBeforeWrite, HTTPService.API, "
            "WebService.DataExchange, AccountingRegister.Accounting, "
            "CalculationRegister.Salary, ChartOfCharacteristicTypes.Properties, "
            "ChartOfAccounts.MainAccounts, ChartOfCalculationTypes.MainCalcs, "
            "BusinessProcess.Approval, Task.Todo, ExchangePlan.Main, "
            "DocumentJournal.Docs); "
            "optional synonym; "
            "for Catalog/Document/Report/DataProcessor/Charts/BusinessProcess/"
            "Task/ExchangePlan: "
            "attributes and tabular_sections; "
            "for Enum: values [{name, synonym?}]; "
            "for registers: dimensions and resources (same shape as attributes); "
            "for AccountingRegister: required chart_of_accounts "
            "(ChartOfAccounts.Name); "
            "for CalculationRegister: required chart_of_calculation_types "
            "(ChartOfCalculationTypes.Name); "
            "for ChartOfCharacteristicTypes: optional value_type / value_types; "
            "for ChartOfAccounts: optional accounting_flags and "
            "ext_dimension_accounting_flags (same shape as attributes); "
            "for BusinessProcess: optional task (Task.Name); "
            "for Task: optional addressing_attributes (same shape as attributes); "
            "for ExchangePlan: optional content [Type.Name] "
            "(applied via add-exchange-content; AutoRecord=Deny in xml-gen); "
            "for DocumentJournal: optional registered_documents [Document.Name] "
            "and columns [{name, references[]}]; "
            "for CommonModule: optional flags server, client "
            "(→ clientManagedApplication), client_ordinary_application, "
            "server_call, external_connection, privileged, global, "
            "return_values_reuse (DontUse|DuringRequest|DuringSession). "
            "BSL body is not written (empty Module.bsl). "
            "for Subsystem: optional content [Type.Name], children [Name], "
            "include_in_command_interface; "
            "for Constant: optional value_type {type, length?/precision?/…}; "
            "for DefinedType: value_type or value_types "
            "[{type, …}, …] (required); "
            "for ScheduledJob: optional method_name "
            "(CommonModule.Name.Method), use, description, key, predefined, "
            "restart_count_on_failure, restart_interval_on_failure; "
            "for EventSubscription: optional handler "
            "(CommonModule.Name.Method), event, source [Type.Name, …]; "
            "for HTTPService: optional root_url, reuse_sessions "
            "(DontUse|Use|AutoUse), session_max_age, url_templates "
            "{Name: {template, methods{Name: GET|POST|…}}}; "
            "for WebService: optional namespace, xdto_packages, reuse_sessions, "
            "session_max_age, operations "
            "{Name: {returnType?, handler?, parameters?}}."
            + _CONFIG_RUNTIME
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
        content: list[str] | None = None,
        children: list[str] | None = None,
        include_in_command_interface: bool | None = None,
        value_type: dict[str, Any] | str | None = None,
        value_types: list[dict[str, Any] | str] | None = None,
        method_name: str | None = None,
        use: bool | None = None,
        description: str | None = None,
        key: str | None = None,
        predefined: bool | None = None,
        restart_count_on_failure: int | None = None,
        restart_interval_on_failure: int | None = None,
        handler: str | None = None,
        event: str | None = None,
        source: list[str] | None = None,
        root_url: str | None = None,
        reuse_sessions: str | None = None,
        session_max_age: int | None = None,
        url_templates: dict[str, Any] | None = None,
        namespace: str | None = None,
        xdto_packages: str | None = None,
        operations: dict[str, Any] | None = None,
        chart_of_accounts: str | None = None,
        chart_of_calculation_types: str | None = None,
        accounting_flags: list[dict[str, Any]] | None = None,
        ext_dimension_accounting_flags: list[dict[str, Any]] | None = None,
        task: str | None = None,
        addressing_attributes: list[dict[str, Any]] | None = None,
        columns: list[dict[str, Any]] | None = None,
        registered_documents: list[str] | None = None,
        path: str | None = None,
        config_id: str | None = None,
        runtime_id: str | None = None,
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
            if accounting_flags:
                data["accountingFlags"] = list(accounting_flags)
            if ext_dimension_accounting_flags:
                data["extDimensionAccountingFlags"] = list(
                    ext_dimension_accounting_flags
                )
            if task is not None:
                data["task"] = task
            if addressing_attributes:
                data["addressingAttributes"] = list(addressing_attributes)
            if columns:
                data["columns"] = list(columns)
            if registered_documents:
                data["registeredDocuments"] = list(registered_documents)
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
            if content:
                data["content"] = list(content)
            if children:
                data["children"] = list(children)
            if include_in_command_interface is not None:
                data["includeInCommandInterface"] = include_in_command_interface
            if value_type is not None:
                data["valueType"] = value_type
            if value_types:
                data["valueTypes"] = list(value_types)
            if method_name is not None:
                data["methodName"] = method_name
            if use is not None:
                data["use"] = use
            if description is not None:
                data["description"] = description
            if key is not None:
                data["key"] = key
            if predefined is not None:
                data["predefined"] = predefined
            if restart_count_on_failure is not None:
                data["restartCountOnFailure"] = restart_count_on_failure
            if restart_interval_on_failure is not None:
                data["restartIntervalOnFailure"] = restart_interval_on_failure
            if handler is not None:
                data["handler"] = handler
            if event is not None:
                data["event"] = event
            if source:
                data["source"] = list(source)
            if root_url is not None:
                data["rootURL"] = root_url
            if reuse_sessions is not None:
                data["reuseSessions"] = reuse_sessions
            if session_max_age is not None:
                data["sessionMaxAge"] = session_max_age
            if url_templates:
                data["urlTemplates"] = dict(url_templates)
            if namespace is not None:
                data["namespace"] = namespace
            if xdto_packages is not None:
                data["xdtoPackages"] = xdto_packages
            if operations:
                data["operations"] = dict(operations)
            if chart_of_accounts is not None:
                data["chartOfAccounts"] = chart_of_accounts
            if chart_of_calculation_types is not None:
                data["chartOfCalculationTypes"] = chart_of_calculation_types
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
        result = create_metadata(
            resolve_path(path),
            catalog,
            config_id=config_id,
            runtime_id=runtime_id,
        )
        return result.to_payload()

    @server.tool(
        name="metadata.update",
        description=(
            "Apply edit operations to an existing metadata object. Prefer "
            "metadata.get first. "
            + _WRITE_TYPES
            + " Pass operations as [{op, value}, …]: "
            "add-attribute / modify-attribute / remove-attribute; "
            "add-ts / modify-ts / remove-ts; add-ts-attribute / remove-ts-attribute; "
            "add-enumValue / modify-enumValue / remove-enumValue; "
            "add-dimension / modify-dimension / remove-dimension; "
            "add-resource / modify-resource / remove-resource; "
            "modify-property; set-flag (CommonModule sugar → modify-property); "
            "for Subsystem: add-content / remove-content / add-child / "
            "remove-child / set-property; "
            "for ExchangePlan: add-exchange-content (value Type.Name; "
            "AutoRecord=Deny in pinned xml-gen). "
            "Examples: {op:'add-attribute', value:'Price:Number(15,2)'}, "
            "{op:'modify-attribute', value:'Price: synonym=Цена'}, "
            "{op:'set-flag', value:'server=true'}, "
            "{op:'add-content', value:'Catalog.Products'}, "
            "{op:'add-exchange-content', value:'Catalog.Products'}. "
            "Does not create new objects — use metadata.create."
            + _CONFIG_RUNTIME
            + _NO_SHELL
        ),
    )
    def metadata_update(
        qualified_name: str,
        operations: list[dict[str, Any]] | None = None,
        path: str | None = None,
        config_id: str | None = None,
        runtime_id: str | None = None,
    ) -> dict[str, Any]:
        parsed = _parse_update_operations(operations)
        if isinstance(parsed, MetadataResult):
            parsed.object = qualified_name
            return parsed.to_payload()
        result = update_metadata(
            resolve_path(path),
            qualified_name,
            parsed,
            config_id=config_id,
            runtime_id=runtime_id,
        )
        return result.to_payload()

    @server.tool(
        name="metadata.delete",
        description=(
            "Delete a whole metadata object from XML source by qualified name "
            "(e.g. Catalog.Products, Subsystem.Main, Constant.VATRate). "
            + _WRITE_TYPES
            + " Removes object artifacts and Configuration.xml registration. "
            "Does not cascade references. Prefer metadata.get first. "
            "To remove attributes/tabular sections/values use metadata.update "
            "remove-* ops instead."
            + _CONFIG_RUNTIME
            + _NO_SHELL
        ),
    )
    def metadata_delete(
        qualified_name: str,
        path: str | None = None,
        config_id: str | None = None,
        runtime_id: str | None = None,
    ) -> dict[str, Any]:
        result = delete_metadata(
            resolve_path(path),
            qualified_name,
            config_id=config_id,
            runtime_id=runtime_id,
        )
        return result.to_payload()

    @server.tool(
        name="build",
        description=(
            "Load XML configuration into a file infobase via ibcmd, then each "
            "nested configurations[].extensions[] (XML) with --extension. "
            "Optional artifact='cf' exports a .cf file for the main configuration."
            + _CONFIG_RUNTIME
            + _NO_SHELL
        ),
    )
    def build_tool(
        path: str | None = None,
        artifact: str | None = None,
        config_id: str | None = None,
        runtime_id: str | None = None,
    ) -> dict[str, Any]:
        result = run_build(
            resolve_path(path),
            artifact=artifact,
            config_id=config_id,
            runtime_id=runtime_id,
        )
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
        name="runtime.start",
        description=(
            "Detach-start the 1C ENTERPRISE client against the project file IB. "
            "client=thick uses 1cv8; client=thin uses 1cv8c (default thick). "
            "Requires a prior build or runtime load. "
            "Set debug=true to pass /Debug (DAP attach is M6)."
            + _CONFIG_RUNTIME
            + _NO_SHELL
        ),
    )
    def runtime_start_tool(
        path: str | None = None,
        client: str = "thick",
        debug: bool = False,
        config_id: str | None = None,
        runtime_id: str | None = None,
    ) -> dict[str, Any]:
        result = run_start(
            resolve_path(path),
            client=client,
            debug=debug,
            config_id=config_id,
            runtime_id=runtime_id,
        )
        return result.to_payload()

    @server.tool(
        name="runtime.stop",
        description=(
            "Stop the detached ENTERPRISE client previously started via runtime.start."
            + _CONFIG_RUNTIME
            + _NO_SHELL
        ),
    )
    def runtime_stop_tool(
        path: str | None = None,
        config_id: str | None = None,
        runtime_id: str | None = None,
    ) -> dict[str, Any]:
        result = run_stop(
            resolve_path(path),
            config_id=config_id,
            runtime_id=runtime_id,
        )
        return result.to_payload()

    @server.tool(
        name="runtime.status",
        description=(
            "Report whether the detached ENTERPRISE client is running "
            "(pid, mode, client, debug.enabled)."
            + _CONFIG_RUNTIME
            + _NO_SHELL
        ),
    )
    def runtime_status_tool(
        path: str | None = None,
        config_id: str | None = None,
        runtime_id: str | None = None,
    ) -> dict[str, Any]:
        result = run_status(
            resolve_path(path),
            config_id=config_id,
            runtime_id=runtime_id,
        )
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
