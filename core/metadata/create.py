"""metadata.create orchestration (ADR-007 / #23 / #24 / #62)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

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
from core.diagnostics import error
from core.metadata.delete import object_xml_path
from core.metadata.ir import CREATE_OBJECT_TYPES, CatalogObject
from core.metadata.read import _resolve_source
from core.metadata.result import MetadataResult
from core.project.validate import validate_project

CompileFn = Callable[[Path, dict[str, Any]], list[str]]
FollowupFn = Callable[[Path, list[EditOp]], None]


def create_metadata(
    start: Path | None,
    catalog: CatalogObject,
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
    compile_fn: CompileFn | None = None,
    followup_fn: FollowupFn | None = None,
) -> MetadataResult:
    """
    Create metadata object via xml-gen write-path (ADR-011 / ADR-018 / #62).

    Supported write types: Meta DSL 23 + Subsystem (see CREATE_OBJECT_TYPES).
    Subsystem uses ``subsystem compile``; others use ``meta compile``.

    compile_fn: optional injectable (source_dir, dsl) -> list[str] for tests.
    followup_fn: optional injectable for tabular-section synonym edits.
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

    resolved = _resolve_source(start, config_id=config_id, runtime_id=runtime_id)
    if isinstance(resolved, MetadataResult):
        return MetadataResult(
            status="error",
            object=catalog.qualified_name,
            root=resolved.root,
            diagnostics=list(resolved.diagnostics),
        )
    root, source_dir, _manifest = resolved
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
