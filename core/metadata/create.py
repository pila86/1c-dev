"""metadata.create orchestration (ADR-007)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from adapters.source.xmlgen import (
    XmlGenError,
    compile_metadata,
    fetch_script_suggestion,
    ir_to_xmlgen_dsl,
    resolve_jar,
    resolve_java,
)
from core.diagnostics import error
from core.metadata.ir import CatalogObject
from core.metadata.result import MetadataResult
from core.project.detect import detect_manifest
from core.project.load import load_manifest
from core.project.validate import validate_project

CompileFn = Callable[[Path, dict[str, Any]], list[str]]


def create_metadata(
    start: Path | None,
    catalog: CatalogObject,
    *,
    compile_fn: CompileFn | None = None,
) -> MetadataResult:
    """
    Create Catalog via xml-gen write-path.

    compile_fn: optional injectable (source_dir, dsl) -> list[str] for tests.
    """
    start_path = (start or Path.cwd()).resolve()
    manifest_path = detect_manifest(start_path)
    if manifest_path is None:
        return MetadataResult(
            status="error",
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
            root=root,
            diagnostics=[
                error(
                    f"source.format={fmt!r}: M1 поддерживает только xml",
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
            root=root,
            diagnostics=[
                error(
                    f"Каталог исходников не найден: {source_dir}",
                    code="1CM001",
                    source="metadata",
                )
            ],
        )

    catalog_file = source_dir / "Catalogs" / f"{catalog.name}.xml"
    if catalog_file.is_file():
        return MetadataResult(
            status="error",
            object=catalog.qualified_name,
            root=root,
            source_path=source_dir,
            diagnostics=[
                error(
                    f"Объект уже существует: {catalog.qualified_name}",
                    code="1CM003",
                    file=str(catalog_file.relative_to(root)),
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

    dsl = ir_to_xmlgen_dsl(catalog.to_dict())
    runner: CompileFn = compile_fn if compile_fn is not None else compile_metadata
    try:
        created_rels = runner(source_dir, dsl)
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
