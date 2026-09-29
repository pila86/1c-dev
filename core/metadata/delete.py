"""metadata.delete orchestration (ADR-011 / #29)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from adapters.source.xmlgen import (
    XmlGenError,
    fetch_script_suggestion,
    remove_metadata,
    resolve_jar,
    resolve_java,
)
from core.diagnostics import error
from core.metadata.ir import IrError, parse_qualified_name
from core.metadata.read import _resolve_source
from core.metadata.result import MetadataResult
from core.metadata.types import TYPE_DIRS

RemoveFn = Callable[[Path, str], list[str]]


def object_xml_path(source_dir: Path, obj_type: str, name: str) -> Path:
    """Return expected object XML path under source_dir for a QName type."""
    folder = TYPE_DIRS.get(obj_type)
    if folder is None:
        raise KeyError(obj_type)
    return source_dir / folder / f"{name}.xml"


def delete_metadata(
    start: Path | None,
    qualified_name: str,
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
    extension_id: str | None = None,
    remove_fn: RemoveFn | None = None,
) -> MetadataResult:
    """
    Delete a whole metadata object via xml-gen meta remove.

    remove_fn: optional injectable (source_dir, qname) -> deleted relative paths.
    extension_id: nested extensions[] id or name (#112).
    """
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

    qname = f"{obj_type}.{name}"
    resolved = _resolve_source(
        start,
        config_id=config_id,
        runtime_id=runtime_id,
        extension_id=extension_id,
    )
    if isinstance(resolved, MetadataResult):
        return MetadataResult(
            status="error",
            object=qname,
            root=resolved.root,
            diagnostics=list(resolved.diagnostics),
        )
    root, source_dir, _manifest = resolved

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

    if remove_fn is None:
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

    runner: RemoveFn = remove_fn if remove_fn is not None else remove_metadata
    try:
        deleted_rels = runner(source_dir, qname)
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

    deleted: list[str] = []
    for rel_src in deleted_rels:
        abs_path = source_dir / rel_src
        try:
            deleted.append(abs_path.relative_to(root).as_posix())
        except ValueError:
            deleted.append(rel_src)

    return MetadataResult(
        status="ok",
        object=qname,
        root=root,
        source_path=source_dir,
        deleted=deleted,
    )
