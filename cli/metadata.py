"""CLI: 1c-dev metadata …"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from adapters.source.xmlgen import EditOp, edit_op_from_dict
from cli.options import ConfigOption, RuntimeOption
from cli.output import OutputFormat, OutputOption, resolve_output
from core.exit_codes import ENV_UNAVAILABLE, PROJECT_ERROR, SUCCESS
from core.metadata import (
    IrError,
    MetadataResult,
    catalog_from_json,
    catalog_from_parts,
    create_metadata,
    delete_metadata,
    find_metadata,
    get_metadata,
    list_metadata,
    load_json_input,
    normalize_edit_ops,
    ops_from_attr,
    ops_from_common_module_flags,
    ops_from_dimension,
    ops_from_enum_value,
    ops_from_resource,
    ops_from_ts,
    ops_from_ts_attr,
    parse_attr_spec,
    parse_enum_value_spec,
    parse_ts_attr_spec,
    parse_ts_spec,
    update_metadata,
)

app = typer.Typer(
    name="metadata",
    help="Семантические операции с метаданными (IR).",
    add_completion=False,
    no_args_is_help=True,
)


def _emit(payload: dict[str, Any], output: OutputFormat, *, text_lines: list[str]) -> None:
    if output is OutputFormat.json:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for line in text_lines:
            typer.echo(line)


def _error_text(result: MetadataResult) -> list[str]:
    lines = ["status: error"]
    for diag in result.diagnostics:
        code = diag.get("code", "")
        prefix = f"[{code}] " if code else ""
        lines.append(f"error: {prefix}{diag.get('message', '')}")
        suggestion = diag.get("suggestion")
        if suggestion:
            lines.append(f"  → {suggestion}")
    return lines


def _create_text(result: MetadataResult) -> list[str]:
    if result.status != "ok":
        return _error_text(result)
    lines = ["status: ok"]
    if result.object:
        lines.append(f"object: {result.object}")
    if result.root:
        lines.append(f"root: {result.root}")
    if result.created:
        lines.append("created:")
        for item in result.created:
            lines.append(f"  - {item}")
    return lines


def _update_text(result: MetadataResult) -> list[str]:
    if result.status != "ok":
        return _error_text(result)
    lines = ["status: ok"]
    if result.object:
        lines.append(f"object: {result.object}")
    if result.root:
        lines.append(f"root: {result.root}")
    if result.updated:
        lines.append("updated:")
        for item in result.updated:
            lines.append(f"  - {item}")
    for diag in result.diagnostics:
        if diag.get("severity") == "warning":
            lines.append(f"warning: {diag.get('message', '')}")
    return lines


def _delete_text(result: MetadataResult) -> list[str]:
    if result.status != "ok":
        return _error_text(result)
    lines = ["status: ok"]
    if result.object:
        lines.append(f"object: {result.object}")
    if result.root:
        lines.append(f"root: {result.root}")
    if result.deleted:
        lines.append("deleted:")
        for item in result.deleted:
            lines.append(f"  - {item}")
    return lines


def _list_text(result: MetadataResult) -> list[str]:
    if result.status != "ok":
        return _error_text(result)
    lines = ["status: ok", f"count: {len(result.objects)}"]
    for obj in result.objects:
        qname = obj.get("qname", "")
        synonym = obj.get("synonym")
        if synonym:
            lines.append(f"  {qname} — {synonym}")
        else:
            lines.append(f"  {qname}")
    return lines


def _get_text(result: MetadataResult) -> list[str]:
    if result.status != "ok":
        return _error_text(result)
    lines = ["status: ok"]
    if result.object:
        lines.append(f"object: {result.object}")
    if result.ir:
        lines.append(json.dumps(result.ir, ensure_ascii=False, indent=2))
    return lines


def _exit_for(result: MetadataResult) -> None:
    if result.status == "ok":
        raise typer.Exit(code=SUCCESS)
    codes = {d.get("code") for d in result.diagnostics}
    if "1CM006" in codes:
        raise typer.Exit(code=ENV_UNAVAILABLE)
    raise typer.Exit(code=PROJECT_ERROR)


def _ir_error_result(exc: IrError) -> MetadataResult:
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
    )


def _build_update_ops(
    *,
    attr: list[str] | None,
    ts: list[str] | None,
    ts_attr: list[str] | None,
    dimension: list[str] | None,
    resource: list[str] | None,
    ops: list[str] | None,
    values: list[str] | None,
    from_json: str | None,
    server: bool | None = None,
    client: bool | None = None,
    client_ordinary: bool | None = None,
    server_call: bool | None = None,
    external_connection: bool | None = None,
    privileged: bool | None = None,
    global_flag: bool | None = None,
    return_values_reuse: str | None = None,
) -> list[EditOp]:
    """Combine sugar, --from-json operations, then --op/--value (with set-flag remap)."""
    result: list[EditOp] = []

    for spec in attr or []:
        attribute = parse_attr_spec(spec)
        result.extend(ops_from_attr(attribute))

    for spec in ts or []:
        section = parse_ts_spec(spec)
        result.extend(ops_from_ts(section))

    for spec in ts_attr or []:
        ts_name, attribute = parse_ts_attr_spec(spec)
        result.extend(ops_from_ts_attr(ts_name, attribute))

    for spec in dimension or []:
        result.extend(ops_from_dimension(parse_attr_spec(spec)))

    for spec in resource or []:
        result.extend(ops_from_resource(parse_attr_spec(spec)))

    result.extend(
        ops_from_common_module_flags(
            server=server,
            client=client,
            client_ordinary_application=client_ordinary,
            server_call=server_call,
            external_connection=external_connection,
            privileged=privileged,
            global_=global_flag,
            return_values_reuse=return_values_reuse,
        )
    )

    if from_json is not None:
        data = load_json_input(from_json)
        raw_ops = data.get("operations")
        if not isinstance(raw_ops, list):
            raise IrError(
                "JSON update ожидает объект с полем operations[]",
                code="1CM002",
            )
        for item in raw_ops:
            if not isinstance(item, dict):
                raise IrError(
                    "Элемент operations должен быть объектом {op, value}",
                    code="1CM002",
                )
            try:
                result.append(edit_op_from_dict(item))
            except ValueError as exc:
                raise IrError(str(exc), code="1CM002") from exc

    op_list = list(ops or [])
    value_list = list(values or [])
    if op_list:
        if len(op_list) != len(value_list):
            raise IrError(
                f"Число --op ({len(op_list)}) должно совпадать с числом --value "
                f"({len(value_list)})",
                code="1CM002",
            )
        for op_name, val in zip(op_list, value_list, strict=True):
            result.append(EditOp(op=op_name, value=val))
    elif value_list:
        # No --op: --value is Enum sugar (Name[:Synonym]).
        for spec in value_list:
            result.extend(ops_from_enum_value(parse_enum_value_spec(spec)))

    if not result:
        raise IrError(
            "Укажите операции: --op/--value, --attr, --ts, --ts-attr, "
            "--dimension, --resource, флаги CommonModule, "
            "subsystem ops (add-content/…) или --from-json",
            code="1CM002",
        )
    return normalize_edit_ops(result)


@app.command("list")
def list_command(
    ctx: typer.Context,
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    output: OutputOption = None,
) -> None:
    """Список объектов метаданных (IR summaries)."""
    fmt = resolve_output(ctx, output)
    result = list_metadata(Path.cwd(), config_id=config, runtime_id=runtime)
    _emit(result.to_payload(), fmt, text_lines=_list_text(result))
    _exit_for(result)


@app.command("get")
def get_command(
    ctx: typer.Context,
    qualified_name: str = typer.Argument(
        ...,
        help="Qualified name, например Catalog.Products.",
    ),
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    output: OutputOption = None,
) -> None:
    """Получить IR объекта по QualifiedName."""
    fmt = resolve_output(ctx, output)
    result = get_metadata(
        Path.cwd(),
        qualified_name,
        config_id=config,
        runtime_id=runtime,
    )
    _emit(result.to_payload(), fmt, text_lines=_get_text(result))
    _exit_for(result)


@app.command("find")
def find_command(
    ctx: typer.Context,
    query: str = typer.Argument(
        ...,
        help="Подстрока имени или синонима.",
    ),
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    output: OutputOption = None,
) -> None:
    """Поиск объектов по имени / синониму."""
    fmt = resolve_output(ctx, output)
    result = find_metadata(Path.cwd(), query, config_id=config, runtime_id=runtime)
    _emit(result.to_payload(), fmt, text_lines=_list_text(result))
    _exit_for(result)


@app.command("update")
def update_command(
    ctx: typer.Context,
    qualified_name: str = typer.Argument(
        ...,
        help=(
            "Qualified name, например Catalog.Products, Enum.Statuses, "
            "InformationRegister.Prices, CommonModule.SalesServer, "
            "Subsystem.Main, Constant.VATRate, DefinedType.CounterpartyRef, "
            "Report.Sales, DataProcessor.ImportData, ScheduledJob.Cleanup, "
            "EventSubscription.ProductsBeforeWrite, HTTPService.API, "
            "WebService.DataExchange, AccountingRegister.Accounting, "
            "CalculationRegister.Salary, ChartOfCharacteristicTypes.Properties, "
            "ChartOfAccounts.MainAccounts, ChartOfCalculationTypes.MainCalcs, "
            "BusinessProcess.Approval, Task.Todo, ExchangePlan.Main, "
            "DocumentJournal.Docs."
        ),
    ),
    op: list[str] | None = typer.Option(
        None,
        "--op",
        help=(
            "Операция: attribute/ts/enumValue/dimension/resource ops, "
            "set-flag, modify-property, add-exchange-content; для Subsystem: "
            "add-content, remove-content, add-child, remove-child, set-property."
        ),
    ),
    value: list[str] | None = typer.Option(
        None,
        "--value",
        help=(
            "С --op: значение операции (zip). Без --op: сахар Enum "
            "Name[:Synonym]."
        ),
    ),
    attr: list[str] | None = typer.Option(
        None,
        "--attr",
        help="Сахар IR Name:Type[:Qual][:Synonym] → add (+ modify synonym).",
    ),
    ts: list[str] | None = typer.Option(
        None,
        "--ts",
        help="Сахар ТЧ Name[:Synonym] → add-ts (+ modify-ts synonym).",
    ),
    ts_attr: list[str] | None = typer.Option(
        None,
        "--ts-attr",
        help="Сахар TSName.Name:Type[:Qual][:Synonym] → add-ts-attribute.",
    ),
    dimension: list[str] | None = typer.Option(
        None,
        "--dimension",
        help="Сахар измерения Name:Type[:Qual][:Synonym] (регистры).",
    ),
    resource: list[str] | None = typer.Option(
        None,
        "--resource",
        help="Сахар ресурса Name:Type[:Qual][:Synonym] (регистры).",
    ),
    server: bool | None = typer.Option(
        None,
        "--server/--no-server",
        help="Флаг Server (CommonModule).",
    ),
    client: bool | None = typer.Option(
        None,
        "--client/--no-client",
        help="Сахар: ClientManagedApplication (CommonModule).",
    ),
    client_ordinary: bool | None = typer.Option(
        None,
        "--client-ordinary/--no-client-ordinary",
        help="Флаг ClientOrdinaryApplication (CommonModule).",
    ),
    server_call: bool | None = typer.Option(
        None,
        "--server-call/--no-server-call",
        help="Флаг ServerCall (CommonModule).",
    ),
    external_connection: bool | None = typer.Option(
        None,
        "--external-connection/--no-external-connection",
        help="Флаг ExternalConnection (CommonModule).",
    ),
    privileged: bool | None = typer.Option(
        None,
        "--privileged/--no-privileged",
        help="Флаг Privileged (CommonModule).",
    ),
    global_flag: bool | None = typer.Option(
        None,
        "--global/--no-global",
        help="Флаг Global (CommonModule).",
    ),
    return_values_reuse: str | None = typer.Option(
        None,
        "--return-values-reuse",
        help="DontUse | DuringRequest | DuringSession (CommonModule).",
    ),
    from_json: str | None = typer.Option(
        None,
        "--from-json",
        help='JSON с operations[] или "-" для stdin.',
    ),
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    output: OutputOption = None,
) -> None:
    """Изменить объект метаданных (Meta DSL 23 + Subsystem)."""
    fmt = resolve_output(ctx, output)
    try:
        operations = _build_update_ops(
            attr=attr,
            ts=ts,
            ts_attr=ts_attr,
            dimension=dimension,
            resource=resource,
            ops=op,
            values=value,
            from_json=from_json,
            server=server,
            client=client,
            client_ordinary=client_ordinary,
            server_call=server_call,
            external_connection=external_connection,
            privileged=privileged,
            global_flag=global_flag,
            return_values_reuse=return_values_reuse,
        )
    except IrError as exc:
        result = _ir_error_result(exc)
        _emit(result.to_payload(), fmt, text_lines=_update_text(result))
        _exit_for(result)
        return
    except (OSError, json.JSONDecodeError) as exc:
        result = MetadataResult(
            status="error",
            diagnostics=[
                {
                    "severity": "error",
                    "code": "1CM004",
                    "message": f"Не удалось прочитать JSON: {exc}",
                    "source": "metadata",
                }
            ],
        )
        _emit(result.to_payload(), fmt, text_lines=_update_text(result))
        _exit_for(result)
        return

    result = update_metadata(
        Path.cwd(),
        qualified_name,
        operations,
        config_id=config,
        runtime_id=runtime,
    )
    _emit(result.to_payload(), fmt, text_lines=_update_text(result))
    _exit_for(result)


@app.command("delete")
def delete_command(
    ctx: typer.Context,
    qualified_name: str = typer.Argument(
        ...,
        help=(
            "Qualified name, например Catalog.Products, Subsystem.Main, "
            "Constant.VATRate, ScheduledJob.Cleanup, BusinessProcess.Approval "
            "(все write-типы: 23 Meta DSL + Subsystem)."
        ),
    ),
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    output: OutputOption = None,
) -> None:
    """Удалить объект метаданных из source (Meta DSL / Subsystem)."""
    fmt = resolve_output(ctx, output)
    result = delete_metadata(
        Path.cwd(),
        qualified_name,
        config_id=config,
        runtime_id=runtime,
    )
    _emit(result.to_payload(), fmt, text_lines=_delete_text(result))
    _exit_for(result)


@app.command("create")
def create_command(
    ctx: typer.Context,
    qualified_name: str = typer.Argument(
        ...,
        help=(
            "Qualified name, например Catalog.Products, Document.Sales, "
            "Enum.Statuses, InformationRegister.Prices, CommonModule.SalesServer, "
            "Subsystem.Main, Constant.VATRate, DefinedType.CounterpartyRef, "
            "Report.Sales, DataProcessor.ImportData, ScheduledJob.Cleanup, "
            "EventSubscription.ProductsBeforeWrite, HTTPService.API, "
            "WebService.DataExchange, AccountingRegister.Accounting, "
            "CalculationRegister.Salary, ChartOfCharacteristicTypes.Properties, "
            "ChartOfAccounts.MainAccounts, ChartOfCalculationTypes.MainCalcs, "
            "BusinessProcess.Approval, Task.Todo, ExchangePlan.Main, "
            "DocumentJournal.Docs."
        ),
    ),
    synonym: str | None = typer.Option(
        None,
        "--synonym",
        help="Синоним объекта.",
    ),
    attr: list[str] | None = typer.Option(
        None,
        "--attr",
        help="Реквизит Name:Type[:Qual][:Synonym], можно повторять.",
    ),
    ts: list[str] | None = typer.Option(
        None,
        "--ts",
        help="Табличная часть Name[:Synonym], можно повторять.",
    ),
    ts_attr: list[str] | None = typer.Option(
        None,
        "--ts-attr",
        help="Реквизит ТЧ: TSName.Name:Type[:Qual][:Synonym], можно повторять.",
    ),
    value: list[str] | None = typer.Option(
        None,
        "--value",
        help="Значение перечисления Name[:Synonym], можно повторять (Enum).",
    ),
    dimension: list[str] | None = typer.Option(
        None,
        "--dimension",
        help="Измерение Name:Type[:Qual][:Synonym] (регистры).",
    ),
    resource: list[str] | None = typer.Option(
        None,
        "--resource",
        help="Ресурс Name:Type[:Qual][:Synonym] (регистры).",
    ),
    server: bool | None = typer.Option(
        None,
        "--server/--no-server",
        help="Флаг Server (CommonModule).",
    ),
    client: bool | None = typer.Option(
        None,
        "--client/--no-client",
        help="Сахар: ClientManagedApplication (CommonModule).",
    ),
    client_ordinary: bool | None = typer.Option(
        None,
        "--client-ordinary/--no-client-ordinary",
        help="Флаг ClientOrdinaryApplication (CommonModule).",
    ),
    server_call: bool | None = typer.Option(
        None,
        "--server-call/--no-server-call",
        help="Флаг ServerCall (CommonModule).",
    ),
    external_connection: bool | None = typer.Option(
        None,
        "--external-connection/--no-external-connection",
        help="Флаг ExternalConnection (CommonModule).",
    ),
    privileged: bool | None = typer.Option(
        None,
        "--privileged/--no-privileged",
        help="Флаг Privileged (CommonModule).",
    ),
    global_flag: bool | None = typer.Option(
        None,
        "--global/--no-global",
        help="Флаг Global (CommonModule).",
    ),
    return_values_reuse: str | None = typer.Option(
        None,
        "--return-values-reuse",
        help="DontUse | DuringRequest | DuringSession (CommonModule).",
    ),
    content: list[str] | None = typer.Option(
        None,
        "--content",
        help="Ссылка Type.Name в составе подсистемы (Subsystem), можно повторять.",
    ),
    child: list[str] | None = typer.Option(
        None,
        "--child",
        help="Имя дочерней подсистемы (Subsystem), можно повторять.",
    ),
    include_in_command_interface: bool | None = typer.Option(
        None,
        "--include-in-command-interface/--no-include-in-command-interface",
        help="IncludeInCommandInterface (Subsystem).",
    ),
    value_type: list[str] | None = typer.Option(
        None,
        "--value-type",
        help=(
            "Тип значения Type[:Qual] для Constant / DefinedType "
            "(например Number:5.2, String:50); можно повторять."
        ),
    ),
    method_name: str | None = typer.Option(
        None,
        "--method-name",
        help="Путь метода CommonModule.Name.Method (ScheduledJob).",
    ),
    use: bool | None = typer.Option(
        None,
        "--use/--no-use",
        help="Флаг Use (ScheduledJob).",
    ),
    description: str | None = typer.Option(
        None,
        "--description",
        help="Description (ScheduledJob).",
    ),
    key: str | None = typer.Option(
        None,
        "--key",
        help="Key уникальности (ScheduledJob).",
    ),
    predefined: bool | None = typer.Option(
        None,
        "--predefined/--no-predefined",
        help="Флаг Predefined (ScheduledJob).",
    ),
    restart_count_on_failure: int | None = typer.Option(
        None,
        "--restart-count-on-failure",
        help="RestartCountOnFailure (ScheduledJob).",
    ),
    restart_interval_on_failure: int | None = typer.Option(
        None,
        "--restart-interval-on-failure",
        help="RestartIntervalOnFailure (ScheduledJob).",
    ),
    handler: str | None = typer.Option(
        None,
        "--handler",
        help="Путь обработчика CommonModule.Name.Method (EventSubscription).",
    ),
    event: str | None = typer.Option(
        None,
        "--event",
        help="Имя события, например BeforeWrite (EventSubscription).",
    ),
    source: list[str] | None = typer.Option(
        None,
        "--source",
        help="Источник Type.Name (EventSubscription), можно повторять.",
    ),
    root_url: str | None = typer.Option(
        None,
        "--root-url",
        help="RootURL (HTTPService).",
    ),
    reuse_sessions: str | None = typer.Option(
        None,
        "--reuse-sessions",
        help="DontUse | Use | AutoUse (HTTPService / WebService).",
    ),
    session_max_age: int | None = typer.Option(
        None,
        "--session-max-age",
        help="SessionMaxAge (HTTPService / WebService).",
    ),
    namespace: str | None = typer.Option(
        None,
        "--namespace",
        help="Namespace URI (WebService).",
    ),
    xdto_packages: str | None = typer.Option(
        None,
        "--xdto-packages",
        help="XDTOPackages (WebService).",
    ),
    chart_of_accounts: str | None = typer.Option(
        None,
        "--chart-of-accounts",
        help="ChartOfAccounts.Name (AccountingRegister).",
    ),
    chart_of_calculation_types: str | None = typer.Option(
        None,
        "--chart-of-calculation-types",
        help="ChartOfCalculationTypes.Name (CalculationRegister).",
    ),
    from_json: str | None = typer.Option(
        None,
        "--from-json",
        help=(
            "Путь к JSON IR или '-' для stdin "
            "(вложенные urlTemplates / operations — через JSON)."
        ),
    ),
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    output: OutputOption = None,
) -> None:
    """Создать объект метаданных (Meta DSL 23 + Subsystem)."""
    fmt = resolve_output(ctx, output)
    try:
        if from_json is not None:
            data = load_json_input(from_json)
            if synonym and "synonym" not in data:
                data["synonym"] = synonym
            if attr:
                existing = list(data.get("attributes") or [])
                existing.extend(attr)
                data["attributes"] = existing
            if value:
                existing_v = list(data.get("values") or [])
                existing_v.extend(value)
                data["values"] = existing_v
            if dimension:
                existing_d = list(data.get("dimensions") or [])
                existing_d.extend(dimension)
                data["dimensions"] = existing_d
            if resource:
                existing_r = list(data.get("resources") or [])
                existing_r.extend(resource)
                data["resources"] = existing_r
            if content:
                existing_c = list(data.get("content") or [])
                existing_c.extend(content)
                data["content"] = existing_c
            if child:
                existing_ch = list(data.get("children") or [])
                existing_ch.extend(child)
                data["children"] = existing_ch
            if value_type:
                existing_vt = list(data.get("valueTypes") or [])
                if "valueType" in data and data["valueType"] is not None:
                    existing_vt.insert(0, data.pop("valueType"))
                existing_vt.extend(value_type)
                data["valueTypes"] = existing_vt
            if (
                include_in_command_interface is not None
                and "includeInCommandInterface" not in data
            ):
                data["includeInCommandInterface"] = include_in_command_interface
            _merge_common_module_cli_flags(
                data,
                server=server,
                client=client,
                client_ordinary=client_ordinary,
                server_call=server_call,
                external_connection=external_connection,
                privileged=privileged,
                global_flag=global_flag,
                return_values_reuse=return_values_reuse,
            )
            _merge_scheduled_job_cli_fields(
                data,
                method_name=method_name,
                use=use,
                description=description,
                key=key,
                predefined=predefined,
                restart_count_on_failure=restart_count_on_failure,
                restart_interval_on_failure=restart_interval_on_failure,
            )
            _merge_event_subscription_cli_fields(
                data,
                handler=handler,
                event=event,
                source=source,
            )
            _merge_http_web_cli_fields(
                data,
                root_url=root_url,
                reuse_sessions=reuse_sessions,
                session_max_age=session_max_age,
                namespace=namespace,
                xdto_packages=xdto_packages,
            )
            _merge_register_chart_cli_fields(
                data,
                chart_of_accounts=chart_of_accounts,
                chart_of_calculation_types=chart_of_calculation_types,
            )
            catalog = catalog_from_json(data, qualified_name=qualified_name)
            if synonym and not catalog.synonym:
                catalog.synonym = synonym
            if ts or ts_attr:
                extra = catalog_from_parts(
                    qualified_name=qualified_name,
                    ts_specs=list(ts or []),
                    ts_attr_specs=list(ts_attr or []),
                )
                # merge CLI TS into JSON-built object
                by_name = {s.name: s for s in catalog.tabular_sections}
                for section in extra.tabular_sections:
                    existing_ts = by_name.get(section.name)
                    if existing_ts is None:
                        catalog.tabular_sections.append(section)
                        by_name[section.name] = section
                    else:
                        if section.synonym and not existing_ts.synonym:
                            existing_ts.synonym = section.synonym
                        existing_names = {a.name for a in existing_ts.attributes}
                        for a in section.attributes:
                            if a.name not in existing_names:
                                existing_ts.attributes.append(a)
        else:
            catalog = catalog_from_parts(
                qualified_name=qualified_name,
                synonym=synonym,
                attr_specs=list(attr or []),
                ts_specs=list(ts or []),
                ts_attr_specs=list(ts_attr or []),
                value_specs=list(value or []),
                dimension_specs=list(dimension or []),
                resource_specs=list(resource or []),
                server=server,
                client=client,
                client_ordinary_application=client_ordinary,
                server_call=server_call,
                external_connection=external_connection,
                privileged=privileged,
                global_=global_flag,
                return_values_reuse=return_values_reuse,
                content=list(content or []),
                children=list(child or []),
                include_in_command_interface=include_in_command_interface,
                value_type_specs=list(value_type or []),
                method_name=method_name,
                use=use,
                description=description,
                key=key,
                predefined=predefined,
                restart_count_on_failure=restart_count_on_failure,
                restart_interval_on_failure=restart_interval_on_failure,
                handler=handler,
                event=event,
                source=list(source or []),
                root_url=root_url,
                reuse_sessions=reuse_sessions,
                session_max_age=session_max_age,
                namespace=namespace,
                xdto_packages=xdto_packages,
                chart_of_accounts=chart_of_accounts,
                chart_of_calculation_types=chart_of_calculation_types,
            )
    except IrError as exc:
        result = _ir_error_result(exc)
        _emit(result.to_payload(), fmt, text_lines=_create_text(result))
        _exit_for(result)
        return
    except (OSError, json.JSONDecodeError) as exc:
        result = MetadataResult(
            status="error",
            diagnostics=[
                {
                    "severity": "error",
                    "code": "1CM004",
                    "message": f"Не удалось прочитать JSON: {exc}",
                    "source": "metadata",
                }
            ],
        )
        _emit(result.to_payload(), fmt, text_lines=_create_text(result))
        _exit_for(result)
        return

    result = create_metadata(
        Path.cwd(),
        catalog,
        config_id=config,
        runtime_id=runtime,
    )
    _emit(result.to_payload(), fmt, text_lines=_create_text(result))
    _exit_for(result)


def _merge_common_module_cli_flags(
    data: dict[str, Any],
    *,
    server: bool | None,
    client: bool | None,
    client_ordinary: bool | None,
    server_call: bool | None,
    external_connection: bool | None,
    privileged: bool | None,
    global_flag: bool | None,
    return_values_reuse: str | None,
) -> None:
    """Fill CommonModule JSON keys from CLI when absent in --from-json body."""
    mapping: list[tuple[str, bool | None]] = [
        ("server", server),
        ("client", client),
        ("clientOrdinaryApplication", client_ordinary),
        ("serverCall", server_call),
        ("externalConnection", external_connection),
        ("privileged", privileged),
        ("global", global_flag),
    ]
    for key, value in mapping:
        if value is not None and key not in data:
            data[key] = value
    if return_values_reuse is not None and "returnValuesReuse" not in data:
        data["returnValuesReuse"] = return_values_reuse


def _merge_scheduled_job_cli_fields(
    data: dict[str, Any],
    *,
    method_name: str | None,
    use: bool | None,
    description: str | None,
    key: str | None,
    predefined: bool | None,
    restart_count_on_failure: int | None,
    restart_interval_on_failure: int | None,
) -> None:
    """Fill ScheduledJob JSON keys from CLI when absent in --from-json body."""
    if method_name is not None and "methodName" not in data:
        data["methodName"] = method_name
    if use is not None and "use" not in data:
        data["use"] = use
    if description is not None and "description" not in data:
        data["description"] = description
    if key is not None and "key" not in data:
        data["key"] = key
    if predefined is not None and "predefined" not in data:
        data["predefined"] = predefined
    if (
        restart_count_on_failure is not None
        and "restartCountOnFailure" not in data
    ):
        data["restartCountOnFailure"] = restart_count_on_failure
    if (
        restart_interval_on_failure is not None
        and "restartIntervalOnFailure" not in data
    ):
        data["restartIntervalOnFailure"] = restart_interval_on_failure


def _merge_event_subscription_cli_fields(
    data: dict[str, Any],
    *,
    handler: str | None,
    event: str | None,
    source: list[str] | None,
) -> None:
    """Fill EventSubscription JSON keys from CLI when absent in --from-json body."""
    if handler is not None and "handler" not in data:
        data["handler"] = handler
    if event is not None and "event" not in data:
        data["event"] = event
    if source:
        existing = list(data.get("source") or [])
        existing.extend(source)
        data["source"] = existing


def _merge_http_web_cli_fields(
    data: dict[str, Any],
    *,
    root_url: str | None,
    reuse_sessions: str | None,
    session_max_age: int | None,
    namespace: str | None,
    xdto_packages: str | None,
) -> None:
    """Fill HTTPService / WebService scalar keys from CLI when absent in JSON."""
    if root_url is not None and "rootURL" not in data:
        data["rootURL"] = root_url
    if reuse_sessions is not None and "reuseSessions" not in data:
        data["reuseSessions"] = reuse_sessions
    if session_max_age is not None and "sessionMaxAge" not in data:
        data["sessionMaxAge"] = session_max_age
    if namespace is not None and "namespace" not in data:
        data["namespace"] = namespace
    if xdto_packages is not None and "xdtoPackages" not in data:
        data["xdtoPackages"] = xdto_packages


def _merge_register_chart_cli_fields(
    data: dict[str, Any],
    *,
    chart_of_accounts: str | None,
    chart_of_calculation_types: str | None,
) -> None:
    """Fill Accounting/CalculationRegister chart refs from CLI when absent."""
    if chart_of_accounts is not None and "chartOfAccounts" not in data:
        data["chartOfAccounts"] = chart_of_accounts
    if (
        chart_of_calculation_types is not None
        and "chartOfCalculationTypes" not in data
    ):
        data["chartOfCalculationTypes"] = chart_of_calculation_types
