"""CLI: 1c-dev metadata …"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from adapters.source.xmlgen import EditOp, edit_op_from_dict
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
    ops_from_attr,
    ops_from_ts,
    ops_from_ts_attr,
    parse_attr_spec,
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
    ops: list[str] | None,
    values: list[str] | None,
    from_json: str | None,
) -> list[EditOp]:
    """Combine --attr/--ts/--ts-attr sugar, --from-json operations, then --op/--value."""
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
    if len(op_list) != len(value_list):
        raise IrError(
            f"Число --op ({len(op_list)}) должно совпадать с числом --value "
            f"({len(value_list)})",
            code="1CM002",
        )
    for op_name, val in zip(op_list, value_list, strict=True):
        result.append(EditOp(op=op_name, value=val))

    if not result:
        raise IrError(
            "Укажите операции: --op/--value, --attr, --ts, --ts-attr или --from-json",
            code="1CM002",
        )
    return result


@app.command("list")
def list_command(
    ctx: typer.Context,
    output: OutputOption = None,
) -> None:
    """Список объектов метаданных (IR summaries)."""
    fmt = resolve_output(ctx, output)
    result = list_metadata(Path.cwd())
    _emit(result.to_payload(), fmt, text_lines=_list_text(result))
    _exit_for(result)


@app.command("get")
def get_command(
    ctx: typer.Context,
    qualified_name: str = typer.Argument(
        ...,
        help="Qualified name, например Catalog.Products.",
    ),
    output: OutputOption = None,
) -> None:
    """Получить IR объекта по QualifiedName."""
    fmt = resolve_output(ctx, output)
    result = get_metadata(Path.cwd(), qualified_name)
    _emit(result.to_payload(), fmt, text_lines=_get_text(result))
    _exit_for(result)


@app.command("find")
def find_command(
    ctx: typer.Context,
    query: str = typer.Argument(
        ...,
        help="Подстрока имени или синонима.",
    ),
    output: OutputOption = None,
) -> None:
    """Поиск объектов по имени / синониму."""
    fmt = resolve_output(ctx, output)
    result = find_metadata(Path.cwd(), query)
    _emit(result.to_payload(), fmt, text_lines=_list_text(result))
    _exit_for(result)


@app.command("update")
def update_command(
    ctx: typer.Context,
    qualified_name: str = typer.Argument(
        ...,
        help="Qualified name, например Catalog.Products или Document.Sales.",
    ),
    op: list[str] | None = typer.Option(
        None,
        "--op",
        help=(
            "Операция xml-gen: add|modify|remove-attribute, "
            "add|modify|remove-ts, add|remove-ts-attribute."
        ),
    ),
    value: list[str] | None = typer.Option(
        None,
        "--value",
        help="Значение для соответствующей --op (порядок zip).",
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
    from_json: str | None = typer.Option(
        None,
        "--from-json",
        help='JSON с operations[] или "-" для stdin.',
    ),
    output: OutputOption = None,
) -> None:
    """Изменить объект метаданных (Catalog/Document: attributes и ТЧ через xml-gen)."""
    fmt = resolve_output(ctx, output)
    try:
        operations = _build_update_ops(
            attr=attr,
            ts=ts,
            ts_attr=ts_attr,
            ops=op,
            values=value,
            from_json=from_json,
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

    result = update_metadata(Path.cwd(), qualified_name, operations)
    _emit(result.to_payload(), fmt, text_lines=_update_text(result))
    _exit_for(result)


@app.command("delete")
def delete_command(
    ctx: typer.Context,
    qualified_name: str = typer.Argument(
        ...,
        help="Qualified name, например Catalog.Products.",
    ),
    output: OutputOption = None,
) -> None:
    """Удалить объект метаданных из source (xml-gen meta remove)."""
    fmt = resolve_output(ctx, output)
    result = delete_metadata(Path.cwd(), qualified_name)
    _emit(result.to_payload(), fmt, text_lines=_delete_text(result))
    _exit_for(result)


@app.command("create")
def create_command(
    ctx: typer.Context,
    qualified_name: str = typer.Argument(
        ...,
        help=(
            "Qualified name, например Catalog.Products, Document.Sales, "
            "Enum.Statuses, InformationRegister.Prices."
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
    from_json: str | None = typer.Option(
        None,
        "--from-json",
        help="Путь к JSON IR или '-' для stdin.",
    ),
    output: OutputOption = None,
) -> None:
    """Создать объект метаданных (Catalog / Document / Enum / регистры) через xml-gen."""
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

    result = create_metadata(Path.cwd(), catalog)
    _emit(result.to_payload(), fmt, text_lines=_create_text(result))
    _exit_for(result)
