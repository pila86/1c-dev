"""metadata.list / get / find orchestration (ADR-012)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from adapters.source.mdclasses import MdReaderError, fetch_script_suggestion, run_md_reader
from core.diagnostics import error
from core.metadata.ir import summary_from_dict
from core.metadata.result import MetadataResult
from core.project.detect import detect_manifest
from core.project.load import load_manifest

Command = Literal["list", "get", "find"]
ReadFn = Callable[[Command, Path, tuple[str, ...]], dict[str, Any]]


def _resolve_source(start: Path | None) -> MetadataResult | tuple[Path, Path, Path]:
    """
    Resolve project root + source dir.

    Returns MetadataResult on error, or (root, source_dir, manifest_path).
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
                    f"source.format={fmt!r}: M2 read поддерживает только xml",
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
    return root, source_dir, manifest_path


def _default_read(command: Command, source_dir: Path, args: tuple[str, ...]) -> dict[str, Any]:
    return run_md_reader(command, source_dir, *args)


def _run_read(
    start: Path | None,
    command: Command,
    *args: str,
    read_fn: ReadFn | None = None,
) -> MetadataResult:
    resolved = _resolve_source(start)
    if isinstance(resolved, MetadataResult):
        return resolved
    root, source_dir, _manifest = resolved

    runner: ReadFn = read_fn if read_fn is not None else _default_read
    try:
        payload = runner(command, source_dir, args)
    except MdReaderError as exc:
        diag_kw: dict[str, Any] = {"code": exc.code, "source": "metadata"}
        if exc.code == "1CM006":
            diag_kw["suggestion"] = (
                f"Соберите md-reader: {fetch_script_suggestion()} "
                "(нужен JDK 17+; или задайте ONEC_MDREADER_JAR)."
            )
        return MetadataResult(
            status="error",
            root=root,
            source_path=source_dir,
            diagnostics=[error(exc.message, **diag_kw)],
        )

    if command in ("list", "find"):
        raw_objects = payload.get("objects") or []
        objects: list[dict[str, Any]] = []
        if isinstance(raw_objects, list):
            for item in raw_objects:
                if isinstance(item, dict):
                    objects.append(summary_from_dict(item).to_dict())
        return MetadataResult(
            status="ok",
            root=root,
            source_path=source_dir,
            objects=objects,
        )

    # get
    ir_raw = payload.get("object")
    if not isinstance(ir_raw, dict):
        return MetadataResult(
            status="error",
            root=root,
            source_path=source_dir,
            diagnostics=[
                error(
                    "md-reader get: отсутствует object в ответе",
                    code="1CM007",
                    source="metadata",
                )
            ],
        )
    qname = str(ir_raw.get("qname") or f"{ir_raw.get('type')}.{ir_raw.get('name')}")
    return MetadataResult(
        status="ok",
        object=qname,
        root=root,
        source_path=source_dir,
        ir=ir_raw,
    )


def list_metadata(
    start: Path | None = None,
    *,
    read_fn: ReadFn | None = None,
) -> MetadataResult:
    """List metadata objects in project source (IR summaries)."""
    return _run_read(start, "list", read_fn=read_fn)


def get_metadata(
    start: Path | None,
    qualified_name: str,
    *,
    read_fn: ReadFn | None = None,
) -> MetadataResult:
    """Get full IR (or stub) for a QualifiedName."""
    return _run_read(start, "get", qualified_name, read_fn=read_fn)


def find_metadata(
    start: Path | None,
    query: str,
    *,
    read_fn: ReadFn | None = None,
) -> MetadataResult:
    """Find metadata objects by name / synonym substring."""
    return _run_read(start, "find", query, read_fn=read_fn)
