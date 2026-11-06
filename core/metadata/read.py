"""metadata.list / get / find orchestration (ADR-012 / ADR-032 #152)."""

from __future__ import annotations

from collections.abc import Callable, Collection
from pathlib import Path
from typing import Any, Literal

from adapters.source.edt import (
    SOURCE_FORMAT_EDT,
    SOURCE_FORMAT_XML,
    EdtSourceError,
    validate_edt_source_dir,
)
from adapters.source.mdclasses import MdReaderError, fetch_script_suggestion, run_md_reader
from core.diagnostics import error
from core.metadata.ir import summary_from_dict
from core.metadata.result import MetadataResult
from core.project.constants import HOME_MANIFEST_REL
from core.project.detect import detect_manifest
from core.project.load import load_manifest
from core.project.paths import scope_root_from_manifest
from core.project.resolve import resolve_config_runtime

Command = Literal["list", "get", "find"]
ReadFn = Callable[[Command, Path, tuple[str, ...]], dict[str, Any]]

# Read (#152) + write semantic (#154): xml | edt.
READ_SOURCE_FORMATS: frozenset[str] = frozenset({SOURCE_FORMAT_XML, SOURCE_FORMAT_EDT})
WRITE_SOURCE_FORMATS: frozenset[str] = frozenset({SOURCE_FORMAT_XML, SOURCE_FORMAT_EDT})


def _lookup_nested_extension(
    configuration: dict[str, Any],
    extension_id: str,
) -> dict[str, Any] | None:
    """Find nested extensions[] entry by id, else by name."""
    raw = configuration.get("extensions")
    if not isinstance(raw, list):
        return None
    by_id: dict[str, Any] | None = None
    by_name: dict[str, Any] | None = None
    for item in raw:
        if not isinstance(item, dict):
            continue
        eid = item.get("id")
        if isinstance(eid, str) and eid == extension_id:
            by_id = item
            break
        ename = item.get("name")
        if by_name is None and isinstance(ename, str) and ename == extension_id:
            by_name = item
    return by_id if by_id is not None else by_name


def _format_not_allowed(
    *,
    fmt: object,
    allowed: Collection[str],
    root: Path,
    manifest_path: Path,
    label: str,
) -> MetadataResult:
    allowed_list = ", ".join(sorted(allowed))
    if label.startswith("extensions["):
        suggestion = (
            "Выгрузите XML через extension add --from *.cfe "
            "или укажите format: xml|edt"
        )
    else:
        suggestion = f"Поддерживаемые форматы для этой операции: {allowed_list}"
    return MetadataResult(
        status="error",
        root=root,
        diagnostics=[
            error(
                f"{label}: source.format={fmt!r}; поддерживается: {allowed_list}",
                code="1CM005",
                file=str(manifest_path),
                source="metadata",
                suggestion=suggestion,
            )
        ],
    )


def _validate_source_dir(
    *,
    fmt: str,
    source_dir: Path,
    root: Path,
    manifest_path: Path,
    label: str,
) -> MetadataResult | None:
    """Return error result if source_dir invalid for format; else None."""
    if not source_dir.is_dir():
        suggestion = (
            "Добавьте расширение через extension add"
            if label.startswith("extensions[")
            else None
        )
        return MetadataResult(
            status="error",
            root=root,
            diagnostics=[
                error(
                    f"Каталог исходников не найден: {source_dir}",
                    code="1CM001",
                    source="metadata",
                    suggestion=suggestion,
                )
            ],
        )
    if fmt == SOURCE_FORMAT_EDT:
        detected = validate_edt_source_dir(source_dir)
        if not detected.is_edt:
            return MetadataResult(
                status="error",
                root=root,
                source_path=source_dir,
                diagnostics=[
                    error(
                        detected.message
                        or f"{label}: путь не является корнем EDT-проекта",
                        code=detected.code or "1CS003",
                        file=str(manifest_path),
                        source="edt",
                        suggestion=detected.suggestion,
                    )
                ],
            )
    return None


def _resolve_source(
    start: Path | None,
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
    extension_id: str | None = None,
    allowed_formats: Collection[str] | None = None,
) -> MetadataResult | tuple[Path, Path, Path, str]:
    """
    Resolve project root + source dir.

    When ``extension_id`` is set, resolves nested ``extensions[]`` source
    (by id or name) under the selected configuration (#112).

    ``allowed_formats`` defaults to read formats (xml|edt, #152).
    Write path passes ``WRITE_SOURCE_FORMATS`` (xml|edt, #154).

    Returns MetadataResult on error, or (root, source_dir, manifest_path, format).
    """
    formats = frozenset(allowed_formats) if allowed_formats is not None else READ_SOURCE_FORMATS
    start_path = (start or Path.cwd()).resolve()
    manifest_path = detect_manifest(start_path)
    if manifest_path is None:
        return MetadataResult(
            status="error",
            diagnostics=[
                error(
                    f"Файл {HOME_MANIFEST_REL} не найден",
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
            root=scope_root_from_manifest(manifest_path),
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

    root = scope_root_from_manifest(manifest_path)
    target, resolve_diags = resolve_config_runtime(
        data,
        config_id=config_id,
        runtime_id=runtime_id,
        require_runtime=False,
    )
    if target is None:
        return MetadataResult(
            status="error",
            root=root,
            diagnostics=list(resolve_diags)
            or [
                error(
                    "Не удалось разрешить --config/--runtime",
                    code="1CM001",
                    source="metadata",
                )
            ],
        )

    if extension_id:
        ext = _lookup_nested_extension(target.configuration, extension_id)
        if ext is None:
            return MetadataResult(
                status="error",
                root=root,
                diagnostics=[
                    error(
                        f"Расширение не найдено: {extension_id!r}",
                        code="1CM001",
                        source="metadata",
                        suggestion=(
                            "Укажите id или name из configurations[].extensions[]; "
                            "добавьте через extension add"
                        ),
                    )
                ],
            )
        source = ext.get("source")
        if not isinstance(source, dict):
            return MetadataResult(
                status="error",
                root=root,
                diagnostics=[
                    error(
                        f"extensions[{extension_id!r}]: отсутствует source",
                        code="1CM001",
                        file=str(manifest_path),
                        source="metadata",
                    )
                ],
            )
        fmt = source.get("format")
        label = f"extensions[{extension_id!r}]"
        if not isinstance(fmt, str) or fmt not in formats:
            return _format_not_allowed(
                fmt=fmt,
                allowed=formats,
                root=root,
                manifest_path=manifest_path,
                label=label,
            )
        path = source.get("path")
        if not isinstance(path, str) or not path:
            return MetadataResult(
                status="error",
                root=root,
                diagnostics=[
                    error(
                        f"extensions[{extension_id!r}]: отсутствует source.path",
                        code="1CM001",
                        file=str(manifest_path),
                        source="metadata",
                    )
                ],
            )
        source_dir = (root / path).resolve()
        invalid = _validate_source_dir(
            fmt=fmt,
            source_dir=source_dir,
            root=root,
            manifest_path=manifest_path,
            label=label,
        )
        if invalid is not None:
            return invalid
        return root, source_dir, manifest_path, fmt

    fmt = target.source_format
    if not isinstance(fmt, str) or fmt not in formats:
        return _format_not_allowed(
            fmt=fmt,
            allowed=formats,
            root=root,
            manifest_path=manifest_path,
            label="configuration",
        )

    rel = target.source_rel
    source_dir = (root / rel).resolve()
    invalid = _validate_source_dir(
        fmt=fmt,
        source_dir=source_dir,
        root=root,
        manifest_path=manifest_path,
        label="configuration",
    )
    if invalid is not None:
        return invalid
    return root, source_dir, manifest_path, fmt


def _default_read(command: Command, source_dir: Path, args: tuple[str, ...]) -> dict[str, Any]:
    return run_md_reader(command, source_dir, *args)


def _run_read(
    start: Path | None,
    command: Command,
    *args: str,
    config_id: str | None = None,
    runtime_id: str | None = None,
    extension_id: str | None = None,
    read_fn: ReadFn | None = None,
) -> MetadataResult:
    resolved = _resolve_source(
        start,
        config_id=config_id,
        runtime_id=runtime_id,
        extension_id=extension_id,
    )
    if isinstance(resolved, MetadataResult):
        return resolved
    root, source_dir, _manifest, _fmt = resolved

    runner: ReadFn = read_fn if read_fn is not None else _default_read
    try:
        payload = runner(command, source_dir, args)
    except EdtSourceError as exc:
        diag_kw_edt: dict[str, Any] = {"code": exc.code, "source": "edt"}
        if exc.suggestion:
            diag_kw_edt["suggestion"] = exc.suggestion
        return MetadataResult(
            status="error",
            root=root,
            source_path=source_dir,
            diagnostics=[error(exc.message, **diag_kw_edt)],
        )
    except MdReaderError as exc:
        diag_kw: dict[str, Any] = {"code": exc.code, "source": "metadata"}
        if exc.code == "1CM006":
            diag_kw["suggestion"] = (
                f"Соберите md-reader: {fetch_script_suggestion()} "
                "(нужен JDK 21+; или задайте ONEC_MDREADER_JAR)."
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
    config_id: str | None = None,
    runtime_id: str | None = None,
    extension_id: str | None = None,
    read_fn: ReadFn | None = None,
) -> MetadataResult:
    """List metadata objects in project source (IR summaries)."""
    return _run_read(
        start,
        "list",
        config_id=config_id,
        runtime_id=runtime_id,
        extension_id=extension_id,
        read_fn=read_fn,
    )


def get_metadata(
    start: Path | None,
    qualified_name: str,
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
    extension_id: str | None = None,
    read_fn: ReadFn | None = None,
) -> MetadataResult:
    """Get full IR (or stub) for a QualifiedName."""
    return _run_read(
        start,
        "get",
        qualified_name,
        config_id=config_id,
        runtime_id=runtime_id,
        extension_id=extension_id,
        read_fn=read_fn,
    )


def find_metadata(
    start: Path | None,
    query: str,
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
    extension_id: str | None = None,
    read_fn: ReadFn | None = None,
) -> MetadataResult:
    """Find metadata objects by name / synonym substring."""
    return _run_read(
        start,
        "find",
        query,
        config_id=config_id,
        runtime_id=runtime_id,
        extension_id=extension_id,
        read_fn=read_fn,
    )
