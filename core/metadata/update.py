"""metadata.update orchestration (ADR-011 / #22)."""

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
from core.metadata.ir import Attribute, IrError, parse_qualified_name
from core.metadata.read import get_metadata
from core.metadata.result import MetadataResult
from core.project.detect import detect_manifest
from core.project.load import load_manifest

EditFn = Callable[[Path, list[EditOp]], EditResult]
GetFn = Callable[..., MetadataResult]


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


def update_metadata(
    start: Path | None,
    qualified_name: str,
    operations: list[EditOp],
    *,
    edit_fn: EditFn | None = None,
    get_fn: GetFn | None = None,
) -> MetadataResult:
    """
    Apply sequential meta-edit ops to an existing Catalog.

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
        obj_type, name = parse_qualified_name(qualified_name)
    except IrError as exc:
        return MetadataResult(
            status="error",
            object=qualified_name,
            diagnostics=[
                error(exc.message, code=exc.code, source="metadata"),
            ],
        )

    if obj_type != "Catalog":
        return MetadataResult(
            status="error",
            object=qualified_name,
            diagnostics=[
                error(
                    f"metadata.update (#22) поддерживает только Catalog.*, "
                    f"получено: {qualified_name!r}",
                    code="1CM002",
                    source="metadata",
                )
            ],
        )

    qname = f"Catalog.{name}"
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

    object_xml = source_dir / "Catalogs" / f"{name}.xml"
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
        edit_result = runner(object_xml, operations)
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
