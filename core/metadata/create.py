"""metadata.create orchestration (ADR-007 / #23 / #24 / #62 / ADR-032 #154)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from adapters.source.edt import SOURCE_FORMAT_EDT, SOURCE_FORMAT_XML
from adapters.source.mdsparrow.constants import GAP_CODE
from adapters.source.mdsparrow.mutation import MdSparrowError
from adapters.source.mdsparrow.paths import object_mdo_path
from adapters.source.mdsparrow.resolve import (
    fetch_script_suggestion as mdsparrow_fetch_suggestion,
)
from adapters.source.mdsparrow.write import create_edt_object
from adapters.source.xmlgen import (
    EditOp,
    XmlGenError,
    compile_metadata,
    compile_subsystem,
    edit_metadata,
    fetch_script_suggestion,
    ir_to_subsystem_dsl,
    ir_to_xmlgen_dsl,
    resolve_jar,
    resolve_java,
)
from core.diagnostics import error, warning
from core.metadata.delete import object_xml_path
from core.metadata.ir import CREATE_OBJECT_TYPES, CatalogObject
from core.metadata.read import WRITE_SOURCE_FORMATS, _resolve_source
from core.metadata.result import MetadataResult
from core.project.validate import validate_project

CompileFn = Callable[[Path, dict[str, Any]], list[str]]
FollowupFn = Callable[[Path, list[EditOp]], None]
EdtCreateFn = Callable[[Path, CatalogObject], Any]


def create_metadata(
    start: Path | None,
    catalog: CatalogObject,
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
    extension_id: str | None = None,
    compile_fn: CompileFn | None = None,
    followup_fn: FollowupFn | None = None,
    edt_create_fn: EdtCreateFn | None = None,
) -> MetadataResult:
    """
    Create metadata object via xml-gen (XML) or md-sparrow (EDT, #154).

    Supported write types: Meta DSL 23 + Subsystem (see CREATE_OBJECT_TYPES).
    Subsystem uses ``subsystem compile``; others use ``meta compile`` (XML).
    EDT uses ``apply-mutation`` (path D).

    compile_fn / followup_fn: injectable for XML unit tests.
    edt_create_fn: injectable for EDT unit tests.
    extension_id: nested extensions[] id or name (#112).
    """
    if catalog.type not in CREATE_OBJECT_TYPES:
        return MetadataResult(
            status="error",
            object=catalog.qualified_name,
            diagnostics=[
                error(
                    f"metadata.create поддерживает только "
                    f"{', '.join(sorted(CREATE_OBJECT_TYPES))}, "
                    f"получено: {catalog.type!r}",
                    code="1CM002",
                    source="metadata",
                )
            ],
        )

    resolved = _resolve_source(
        start,
        config_id=config_id,
        runtime_id=runtime_id,
        extension_id=extension_id,
        allowed_formats=WRITE_SOURCE_FORMATS,
    )
    if isinstance(resolved, MetadataResult):
        return MetadataResult(
            status="error",
            object=catalog.qualified_name,
            root=resolved.root,
            diagnostics=list(resolved.diagnostics),
        )
    root, source_dir, _manifest, fmt = resolved

    if fmt == SOURCE_FORMAT_EDT:
        return _create_edt(
            root,
            source_dir,
            catalog,
            edt_create_fn=edt_create_fn,
        )
    if fmt != SOURCE_FORMAT_XML:
        return MetadataResult(
            status="error",
            object=catalog.qualified_name,
            root=root,
            source_path=source_dir,
            diagnostics=[
                error(
                    f"configuration: source.format={fmt!r}; поддерживается: "
                    f"{', '.join(sorted(WRITE_SOURCE_FORMATS))}",
                    code="1CM005",
                    source="metadata",
                )
            ],
        )

    return _create_xml(
        root,
        source_dir,
        catalog,
        compile_fn=compile_fn,
        followup_fn=followup_fn,
    )


def _create_edt(
    root: Path,
    source_dir: Path,
    catalog: CatalogObject,
    *,
    edt_create_fn: EdtCreateFn | None,
) -> MetadataResult:
    object_file = object_mdo_path(source_dir, catalog.type, catalog.name)
    if object_file.is_file():
        try:
            file_rel = object_file.relative_to(root).as_posix()
        except ValueError:
            file_rel = str(object_file)
        return MetadataResult(
            status="error",
            object=catalog.qualified_name,
            root=root,
            source_path=source_dir,
            diagnostics=[
                error(
                    f"Объект уже существует: {catalog.qualified_name}",
                    code="1CM003",
                    file=file_rel,
                    source="metadata",
                )
            ],
        )

    runner = edt_create_fn if edt_create_fn is not None else create_edt_object
    try:
        write_result = runner(source_dir, catalog)
    except MdSparrowError as exc:
        diag_kw: dict[str, Any] = {
            "code": exc.code,
            "source": "metadata" if exc.code.startswith("1CM") else "edt",
        }
        if getattr(exc, "suggestion", None):
            diag_kw["suggestion"] = exc.suggestion
        elif exc.code in {"1CS008", "1CM006"}:
            diag_kw["suggestion"] = mdsparrow_fetch_suggestion()
        return MetadataResult(
            status="error",
            object=catalog.qualified_name,
            root=root,
            source_path=source_dir,
            diagnostics=[error(exc.message, **diag_kw)],
        )

    created = list(getattr(write_result, "changed_paths", []) or [])
    warn_msgs = list(getattr(write_result, "warnings", None) or [])
    warn_codes = list(getattr(write_result, "warning_codes", None) or [])
    gap_warnings = []
    for i, msg in enumerate(warn_msgs):
        code = warn_codes[i] if i < len(warn_codes) else None
        if code is None and ("gap" in msg.lower() or GAP_CODE in msg):
            code = GAP_CODE
        gap_warnings.append(warning(msg, code=code, source="edt"))

    validated = validate_project(root)
    if validated.status != "ok":
        return MetadataResult(
            status="error",
            object=catalog.qualified_name,
            root=root,
            source_path=source_dir,
            created=created,
            diagnostics=list(validated.diagnostics) + gap_warnings,
        )

    return MetadataResult(
        status="ok",
        object=catalog.qualified_name,
        root=root,
        source_path=source_dir,
        created=created,
        diagnostics=gap_warnings,
    )


def _create_xml(
    root: Path,
    source_dir: Path,
    catalog: CatalogObject,
    *,
    compile_fn: CompileFn | None,
    followup_fn: FollowupFn | None,
) -> MetadataResult:
    object_file = object_xml_path(source_dir, catalog.type, catalog.name)
    if object_file.is_file():
        try:
            file_rel = object_file.relative_to(root).as_posix()
        except ValueError:
            file_rel = str(object_file)
        return MetadataResult(
            status="error",
            object=catalog.qualified_name,
            root=root,
            source_path=source_dir,
            diagnostics=[
                error(
                    f"Объект уже существует: {catalog.qualified_name}",
                    code="1CM003",
                    file=file_rel,
                    source="metadata",
                )
            ],
        )

    # Injectable compile_fn skips real toolchain (unit tests).
    if compile_fn is None:
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
                object=catalog.qualified_name,
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

    if catalog.type == "Subsystem":
        dsl = ir_to_subsystem_dsl(catalog.to_dict())
        runner: CompileFn = (
            compile_fn if compile_fn is not None else compile_subsystem
        )
    else:
        dsl = ir_to_xmlgen_dsl(catalog.to_dict())
        runner = compile_fn if compile_fn is not None else compile_metadata

    try:
        created_rels = runner(source_dir, dsl)
        if catalog.type != "Subsystem":
            _apply_tabular_synonyms(
                object_file,
                catalog,
                followup_fn=followup_fn,
            )
            _apply_exchange_plan_content(
                object_file,
                catalog,
                followup_fn=followup_fn,
            )
    except XmlGenError as exc:
        diag_kw: dict[str, Any] = {
            "code": exc.code,
            "source": "metadata",
        }
        if exc.code == "1CM006":
            diag_kw["suggestion"] = fetch_script_suggestion()
        return MetadataResult(
            status="error",
            object=catalog.qualified_name,
            root=root,
            source_path=source_dir,
            diagnostics=[error(exc.message, **diag_kw)],
        )

    created: list[str] = []
    for rel_src in created_rels:
        abs_path = source_dir / rel_src
        try:
            created.append(abs_path.relative_to(root).as_posix())
        except ValueError:
            created.append(rel_src)

    validated = validate_project(root)
    if validated.status != "ok":
        return MetadataResult(
            status="error",
            object=catalog.qualified_name,
            root=root,
            source_path=source_dir,
            created=created,
            diagnostics=list(validated.diagnostics),
        )

    return MetadataResult(
        status="ok",
        object=catalog.qualified_name,
        root=root,
        source_path=source_dir,
        created=created,
    )


def _apply_tabular_synonyms(
    object_file: Path,
    catalog: CatalogObject,
    *,
    followup_fn: FollowupFn | None,
) -> None:
    """Apply TS synonyms via meta edit modify-ts (xml-gen compile map has no synonym)."""
    ops = [
        EditOp(op="modify-ts", value=f"{section.name}: synonym={section.synonym}")
        for section in catalog.tabular_sections
        if section.synonym
    ]
    if not ops:
        return
    _run_followup_edits(object_file, ops, followup_fn=followup_fn)


def _apply_exchange_plan_content(
    object_file: Path,
    catalog: CatalogObject,
    *,
    followup_fn: FollowupFn | None,
) -> None:
    """Apply ExchangePlan content via add-exchange-content.

    xml-gen ``meta compile`` writes an empty Content.xml stub and ignores DSL
    ``content``; AutoRecord is always Deny in the pinned xml-gen (#69 gap).
    """
    if catalog.type != "ExchangePlan" or not catalog.content:
        return
    ops = [
        EditOp(op="add-exchange-content", value=qname)
        for qname in catalog.content
    ]
    _run_followup_edits(object_file, ops, followup_fn=followup_fn)


def _run_followup_edits(
    object_file: Path,
    ops: list[EditOp],
    *,
    followup_fn: FollowupFn | None,
) -> None:
    if followup_fn is not None:
        followup_fn(object_file, ops)
        return
    if not object_file.is_file():
        raise XmlGenError(
            f"Файл объекта не найден после compile: {object_file}",
            code="1CM007",
        )
    edit_metadata(object_file, ops)
