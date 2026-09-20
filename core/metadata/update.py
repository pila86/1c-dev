"""metadata.update orchestration (ADR-011 / #22 / #35 / #39 / #40)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from adapters.source.xmlgen import (
    EditOp,
    EditResult,
    XmlGenError,
    edit_metadata,
    fetch_script_suggestion,
    resolve_jar,
    resolve_java,
)
from core.diagnostics import error, warning
from core.metadata.delete import object_xml_path
from core.metadata.ir import (
    UPDATE_OBJECT_TYPES,
    Attribute,
    EnumValue,
    IrError,
    TabularSection,
    parse_qualified_name,
)
from core.metadata.read import get_metadata
from core.metadata.result import MetadataResult
from core.project.detect import detect_manifest
from core.project.load import load_manifest

EditFn = Callable[[Path, list[EditOp]], EditResult]
GetFn = Callable[..., MetadataResult]

# Public sugar op (not in xml-gen ALLOWED_OPS) → remapped to modify-property.
_SET_FLAG_OP = "set-flag"

# IR / CLI flag name → Designer XML property name.
_FLAG_TO_PROPERTY: dict[str, str] = {
    "server": "Server",
    "client": "ClientManagedApplication",
    "clientmanagedapplication": "ClientManagedApplication",
    "clientordinaryapplication": "ClientOrdinaryApplication",
    "servercall": "ServerCall",
    "externalconnection": "ExternalConnection",
    "privileged": "Privileged",
    "global": "Global",
    "returnvaluesreuse": "ReturnValuesReuse",
}

_RETURN_VALUES_REUSE: frozenset[str] = frozenset(
    {"DontUse", "DuringRequest", "DuringSession"}
)


def attr_to_xmlgen_shorthand(attr: Attribute) -> str:
    """Map IR Attribute to xml-gen add-attribute type shorthand (no synonym)."""
    if attr.type == "String":
        length = int(attr.length or 10)
        type_spec = f"String({length})"
    elif attr.type == "Number":
        precision = int(attr.precision or 15)
        scale = int(attr.scale or 2)
        type_spec = f"Number({precision},{scale})"
    elif attr.type == "Boolean":
        type_spec = "Boolean"
    elif attr.type == "Date":
        type_spec = "Date"
    elif attr.type == "Ref":
        if not attr.reference:
            raise ValueError(f"Ref-атрибут {attr.name!r} без reference")
        type_part, name_part = attr.reference.split(".", 1)
        type_spec = f"{type_part}Ref.{name_part}"
    else:
        raise ValueError(f"Неподдерживаемый тип атрибута: {attr.type!r}")
    return f"{attr.name}:{type_spec}"


def ops_from_attr(attr: Attribute) -> list[EditOp]:
    """Expand IR Attribute into add-attribute (+ optional modify synonym)."""
    ops = [EditOp(op="add-attribute", value=attr_to_xmlgen_shorthand(attr))]
    if attr.synonym:
        ops.append(
            EditOp(
                op="modify-attribute",
                value=f"{attr.name}: synonym={attr.synonym}",
            )
        )
    return ops


def ops_from_ts(section: TabularSection) -> list[EditOp]:
    """Expand TabularSection into add-ts (+ optional modify-ts synonym)."""
    ops = [EditOp(op="add-ts", value=section.name)]
    if section.synonym:
        ops.append(
            EditOp(
                op="modify-ts",
                value=f"{section.name}: synonym={section.synonym}",
            )
        )
    return ops


def ops_from_ts_attr(ts_name: str, attr: Attribute) -> list[EditOp]:
    """
    Expand TS attribute into add-ts-attribute.

    Synonym is accepted by CLI sugar for create-compat but not emitted:
    pinned xml-gen has no modify-ts-attribute.
    """
    shorthand = attr_to_xmlgen_shorthand(attr)
    return [EditOp(op="add-ts-attribute", value=f"{ts_name}.{shorthand}")]


def ops_from_enum_value(value: EnumValue) -> list[EditOp]:
    """Expand EnumValue into add-enumValue (+ optional modify synonym)."""
    ops = [EditOp(op="add-enumValue", value=value.name)]
    if value.synonym:
        ops.append(
            EditOp(
                op="modify-enumValue",
                value=f"{value.name}: synonym={value.synonym}",
            )
        )
    return ops


def ops_from_dimension(attr: Attribute) -> list[EditOp]:
    """Expand IR Attribute into add-dimension (+ optional modify synonym)."""
    ops = [EditOp(op="add-dimension", value=attr_to_xmlgen_shorthand(attr))]
    if attr.synonym:
        ops.append(
            EditOp(
                op="modify-dimension",
                value=f"{attr.name}: synonym={attr.synonym}",
            )
        )
    return ops


def ops_from_resource(attr: Attribute) -> list[EditOp]:
    """Expand IR Attribute into add-resource (+ optional modify synonym)."""
    ops = [EditOp(op="add-resource", value=attr_to_xmlgen_shorthand(attr))]
    if attr.synonym:
        ops.append(
            EditOp(
                op="modify-resource",
                value=f"{attr.name}: synonym={attr.synonym}",
            )
        )
    return ops


def ops_from_set_flag(value: str) -> list[EditOp]:
    """
    Expand set-flag sugar ``name=value`` into modify-property.

    Accepts IR/CLI names (server, client, …) or Designer names (Server, …).
    """
    raw = value.strip()
    if not raw or "=" not in raw:
        raise IrError(
            "set-flag ожидает значение вида name=value "
            "(например server=true или ReturnValuesReuse=DuringRequest)",
            code="1CM002",
        )
    name_part, val_part = raw.split("=", 1)
    flag_name = name_part.strip()
    flag_value = val_part.strip()
    if not flag_name or not flag_value:
        raise IrError(
            "set-flag ожидает значение вида name=value",
            code="1CM002",
        )
    prop = _resolve_flag_property(flag_name)
    normalized = _normalize_flag_value(prop, flag_value)
    return [EditOp(op="modify-property", value=f"{prop}={normalized}")]


def ops_from_common_module_flags(
    *,
    server: bool | None = None,
    client: bool | None = None,
    client_managed_application: bool | None = None,
    client_ordinary_application: bool | None = None,
    server_call: bool | None = None,
    external_connection: bool | None = None,
    privileged: bool | None = None,
    global_: bool | None = None,
    return_values_reuse: str | None = None,
) -> list[EditOp]:
    """Build modify-property ops from CLI CommonModule flag options."""
    managed = client_managed_application
    if client is not None:
        managed = client if managed is None else managed

    pairs: list[tuple[str, bool | None]] = [
        ("Server", server),
        ("ClientManagedApplication", managed),
        ("ClientOrdinaryApplication", client_ordinary_application),
        ("ServerCall", server_call),
        ("ExternalConnection", external_connection),
        ("Privileged", privileged),
        ("Global", global_),
    ]
    ops: list[EditOp] = []
    for prop, val in pairs:
        if val is not None:
            ops.append(
                EditOp(
                    op="modify-property",
                    value=f"{prop}={'true' if val else 'false'}",
                )
            )
    if return_values_reuse is not None:
        reuse = return_values_reuse.strip()
        if reuse not in _RETURN_VALUES_REUSE:
            raise IrError(
                "returnValuesReuse должен быть одним из: "
                + ", ".join(sorted(_RETURN_VALUES_REUSE)),
                code="1CM002",
            )
        ops.append(
            EditOp(
                op="modify-property",
                value=f"ReturnValuesReuse={reuse}",
            )
        )
    return ops


def normalize_edit_ops(operations: list[EditOp]) -> list[EditOp]:
    """Remap public sugar ops (set-flag) to xml-gen wire ops."""
    result: list[EditOp] = []
    for op in operations:
        if op.op == _SET_FLAG_OP:
            result.extend(ops_from_set_flag(op.value))
        else:
            result.append(op)
    return result


def _resolve_flag_property(name: str) -> str:
    key = name.strip()
    lower = key.lower().replace("_", "")
    if lower in _FLAG_TO_PROPERTY:
        return _FLAG_TO_PROPERTY[lower]
    # Already Designer-cased property name.
    known = {v.lower(): v for v in _FLAG_TO_PROPERTY.values()}
    if lower in known:
        return known[lower]
    raise IrError(
        f"Неизвестный флаг CommonModule: {name!r}",
        code="1CM002",
    )


def _normalize_flag_value(prop: str, value: str) -> str:
    if prop == "ReturnValuesReuse":
        if value not in _RETURN_VALUES_REUSE:
            raise IrError(
                "returnValuesReuse должен быть одним из: "
                + ", ".join(sorted(_RETURN_VALUES_REUSE)),
                code="1CM002",
            )
        return value
    lower = value.lower()
    if lower in {"true", "1", "yes"}:
        return "true"
    if lower in {"false", "0", "no"}:
        return "false"
    raise IrError(
        f"Флаг {prop} ожидает true/false, получено: {value!r}",
        code="1CM002",
    )


def update_metadata(
    start: Path | None,
    qualified_name: str,
    operations: list[EditOp],
    *,
    edit_fn: EditFn | None = None,
    get_fn: GetFn | None = None,
) -> MetadataResult:
    """
    Apply sequential meta-edit ops to an existing metadata object.

    edit_fn / get_fn: injectable for unit tests.
    """
    if not operations:
        return MetadataResult(
            status="error",
            object=qualified_name,
            diagnostics=[
                error(
                    "Список операций пуст",
                    code="1CM002",
                    source="metadata",
                )
            ],
        )

    try:
        wire_ops = normalize_edit_ops(operations)
    except IrError as exc:
        return MetadataResult(
            status="error",
            object=qualified_name,
            diagnostics=[
                error(exc.message, code=exc.code, source="metadata"),
            ],
        )

    try:
        obj_type, name = parse_qualified_name(qualified_name)
    except IrError as exc:
        return MetadataResult(
            status="error",
            object=qualified_name,
            diagnostics=[
                error(exc.message, code=exc.code, source="metadata"),
            ],
        )

    if obj_type not in UPDATE_OBJECT_TYPES:
        return MetadataResult(
            status="error",
            object=qualified_name,
            diagnostics=[
                error(
                    f"metadata.update поддерживает только "
                    f"{', '.join(sorted(UPDATE_OBJECT_TYPES))}.*, "
                    f"получено: {qualified_name!r}",
                    code="1CM002",
                    source="metadata",
                )
            ],
        )

    qname = f"{obj_type}.{name}"
    start_path = (start or Path.cwd()).resolve()
    manifest_path = detect_manifest(start_path)
    if manifest_path is None:
        return MetadataResult(
            status="error",
            object=qname,
            diagnostics=[
                error(
                    "Файл 1c.project.yaml не найден",
                    code="1CM001",
                    source="metadata",
                    suggestion="Выполните 1c-dev init --type configuration",
                )
            ],
        )

    data, load_diags = load_manifest(manifest_path)
    if data is None:
        return MetadataResult(
            status="error",
            object=qname,
            root=manifest_path.parent,
            diagnostics=list(load_diags)
            or [
                error(
                    "Не удалось прочитать манифест",
                    code="1CM001",
                    file=str(manifest_path),
                    source="metadata",
                )
            ],
        )

    root = manifest_path.parent
    source_raw = data.get("source")
    source: dict[str, Any] = source_raw if isinstance(source_raw, dict) else {}
    fmt = source.get("format")
    if fmt != "xml":
        return MetadataResult(
            status="error",
            object=qname,
            root=root,
            diagnostics=[
                error(
                    f"source.format={fmt!r}: M2 update поддерживает только xml",
                    code="1CM005",
                    file=str(manifest_path),
                    source="metadata",
                )
            ],
        )

    rel = str(source.get("path") or "src/cf")
    source_dir = (root / rel).resolve()
    if not source_dir.is_dir():
        return MetadataResult(
            status="error",
            object=qname,
            root=root,
            diagnostics=[
                error(
                    f"Каталог исходников не найден: {source_dir}",
                    code="1CM001",
                    source="metadata",
                )
            ],
        )

    object_xml = object_xml_path(source_dir, obj_type, name)
    if not object_xml.is_file():
        try:
            file_rel = object_xml.relative_to(root).as_posix()
        except ValueError:
            file_rel = str(object_xml)
        return MetadataResult(
            status="error",
            object=qname,
            root=root,
            source_path=source_dir,
            diagnostics=[
                error(
                    f"Объект не найден: {qname}",
                    code="1CM008",
                    file=file_rel,
                    source="metadata",
                )
            ],
        )

    if edit_fn is None:
        java = resolve_java()
        jar = resolve_jar()
        if not java.found or not jar.found:
            missing: list[str] = []
            if not java.found:
                missing.append("Java 17+")
            if not jar.found:
                missing.append("xml-gen")
            return MetadataResult(
                status="error",
                object=qname,
                root=root,
                source_path=source_dir,
                diagnostics=[
                    error(
                        f"Недоступно: {', '.join(missing)}",
                        code="1CM006",
                        source="metadata",
                        suggestion=(
                            f"Соберите xml-gen: {fetch_script_suggestion()} "
                            "(нужен JDK 17+; или задайте ONEC_XMLGEN_JAR)."
                        ),
                    )
                ],
            )

    runner: EditFn = edit_fn if edit_fn is not None else _default_edit
    try:
        edit_result = runner(object_xml, wire_ops)
    except XmlGenError as exc:
        diag_kw: dict[str, Any] = {
            "code": exc.code,
            "source": "metadata",
        }
        if exc.code == "1CM006":
            diag_kw["suggestion"] = (
                f"Соберите xml-gen: {fetch_script_suggestion()} "
                "(нужен JDK 17+; или задайте ONEC_XMLGEN_JAR)."
            )
        return MetadataResult(
            status="error",
            object=qname,
            root=root,
            source_path=source_dir,
            diagnostics=[error(exc.message, **diag_kw)],
        )

    updated: list[str] = []
    for rel_src in edit_result.changed_paths:
        abs_path = Path(rel_src)
        if not abs_path.is_absolute():
            abs_path = (source_dir / rel_src).resolve()
        try:
            updated.append(abs_path.relative_to(root).as_posix())
        except ValueError:
            updated.append(rel_src)

    diagnostics = [
        warning(msg, source="metadata") for msg in edit_result.warnings
    ]

    getter: GetFn = get_fn if get_fn is not None else get_metadata
    get_result = getter(start_path, qname)
    ir = get_result.ir if get_result.status == "ok" else None
    if get_result.status != "ok":
        diagnostics.extend(list(get_result.diagnostics))

    return MetadataResult(
        status="ok",
        object=qname,
        root=root,
        source_path=source_dir,
        updated=updated,
        ir=ir,
        diagnostics=diagnostics,
    )


def _default_edit(object_xml: Path, operations: list[EditOp]) -> EditResult:
    return edit_metadata(object_xml, operations)
