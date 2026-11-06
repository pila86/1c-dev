"""Orchestration: source.convert XML ↔ EDT (ADR-032 / #156)."""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from adapters.edtcli import (
    CODE_EDTCLI_MISSING,
    DEFAULT_IMPORT_PLATFORM_VERSION,
    EdtCliError,
    EdtCliInfo,
    RunFn,
    export_configuration,
    import_configuration,
    require_edtcli,
)
from adapters.source.edt.detect import validate_edt_source_dir
from core.configuration.register import write_manifest_yaml
from core.diagnostics import Diagnostic, error
from core.project.constants import MANIFEST_NAME
from core.project.detect import detect_manifest
from core.project.load import load_manifest
from core.project.paths import scope_root_from_manifest
from core.project.resolve import resolve_config_runtime
from core.source.constants import (
    CODE_CONVERT_DIRTY,
    CODE_PROJECT_MISSING,
    CONVERT_TARGETS,
    ROOT_PRESERVE_NAMES,
    SOURCE_FORMAT_EDT,
    SOURCE_FORMAT_XML,
)
from core.source.result import ConvertResult

ConvertTarget = Literal["edt", "xml"]


def _platform_version(data: dict[str, Any]) -> str:
    platform = data.get("platform")
    if isinstance(platform, dict):
        raw = platform.get("version")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return DEFAULT_IMPORT_PLATFORM_VERSION


def _preserve_names_for(directory: Path, *, root: Path) -> frozenset[str]:
    """Names kept when ``directory`` is the project root."""
    if directory.resolve() == root.resolve():
        return ROOT_PRESERVE_NAMES
    return frozenset()


def _clear_directory_contents(
    directory: Path,
    *,
    root: Path,
) -> None:
    """
    Remove children of ``directory``.

    When ``directory`` is the project root, preserve ``ROOT_PRESERVE_NAMES``
    (``.1c-dev``, ``.git``, …) — same safety as ``project.clean``.
    """
    if not directory.exists():
        directory.mkdir(parents=True, exist_ok=True)
        return
    if not directory.is_dir():
        raise OSError(f"source.path не каталог: {directory}")

    preserve = _preserve_names_for(directory, root=root)
    for child in list(directory.iterdir()):
        if child.name in preserve:
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink(missing_ok=False)


def _copy_tree_into(src: Path, dest: Path) -> None:
    """Copy all children of ``src`` into existing ``dest``."""
    dest.mkdir(parents=True, exist_ok=True)
    for child in src.iterdir():
        target = dest / child.name
        if child.is_dir() and not child.is_symlink():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(child, target)
        else:
            shutil.copy2(child, target)


def _move_replaceable_into(
    source_dir: Path,
    backup_dir: Path,
    *,
    root: Path,
) -> None:
    """
    Move replaceable children of ``source_dir`` into ``backup_dir``.

    Preserves ``ROOT_PRESERVE_NAMES`` when ``source_dir`` is the project root.
    Leaves ``source_dir`` with only preserved entries (or empty).
    """
    backup_dir.mkdir(parents=True, exist_ok=True)
    if not source_dir.exists():
        source_dir.mkdir(parents=True, exist_ok=True)
        return
    if not source_dir.is_dir():
        raise OSError(f"source.path не каталог: {source_dir}")

    preserve = _preserve_names_for(source_dir, root=root)
    for child in list(source_dir.iterdir()):
        if child.name in preserve:
            continue
        shutil.move(str(child), str(backup_dir / child.name))


def _rollback_source_from_backup(
    source_dir: Path,
    backup_dir: Path,
    *,
    root: Path,
) -> None:
    """Best-effort restore of ``source_dir`` from ``backup_dir`` after a failed swap."""
    _clear_directory_contents(source_dir, root=root)
    if backup_dir.is_dir():
        _copy_tree_into(backup_dir, source_dir)


def _write_manifest_atomic(manifest_path: Path, data: dict[str, Any]) -> None:
    """Write project.yaml via temp file + ``os.replace`` (no half-written manifest)."""
    tmp = manifest_path.with_name(f"{manifest_path.name}.{os.getpid()}.tmp")
    try:
        write_manifest_yaml(tmp, data)
        os.replace(tmp, manifest_path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _stage_xml_for_import(source_dir: Path, staging_xml: Path, *, root: Path) -> Path:
    """
    Copy Designer XML into a clean temp dir for ``1cedtcli import``.

    When ``source.path`` is the project root, excludes ``ROOT_PRESERVE_NAMES``
    so ``.1c-dev`` / ``.git`` do not enter ``--configuration-files``.
    """
    staging_xml.mkdir(parents=True, exist_ok=True)
    preserve = _preserve_names_for(source_dir, root=root)
    for child in source_dir.iterdir():
        if child.name in preserve:
            continue
        target = staging_xml / child.name
        if child.is_dir() and not child.is_symlink():
            shutil.copytree(child, target)
        else:
            shutil.copy2(child, target)
    if not (staging_xml / "Configuration.xml").is_file():
        raise OSError(f"Нет Configuration.xml после staging из {source_dir}")
    return staging_xml


def _update_source_format(
    data: dict[str, Any],
    *,
    config_id: str,
    fmt: str,
    path_rel: str,
) -> None:
    configurations = data.get("configurations")
    if not isinstance(configurations, list):
        return
    for item in configurations:
        if not isinstance(item, dict) or item.get("id") != config_id:
            continue
        source = item.get("source")
        if not isinstance(source, dict):
            source = {}
            item["source"] = source
        source["format"] = fmt
        source["path"] = path_rel
        return


def _failed(
    *,
    started: float,
    root: Path | None,
    diagnostics: list[Diagnostic],
    config_id: str | None = None,
    source_path: Path | None = None,
    source_rel: str | None = None,
    from_format: str | None = None,
    to_format: str | None = None,
    steps: list[str] | None = None,
) -> ConvertResult:
    return ConvertResult(
        status="failed",
        duration=time.perf_counter() - started,
        root=root,
        config_id=config_id,
        source_path=source_path,
        source_rel=source_rel,
        from_format=from_format,
        to_format=to_format,
        steps=list(steps or []),
        diagnostics=diagnostics,
    )


def run_convert(
    start: Path | None = None,
    *,
    to: ConvertTarget,
    config_id: str | None = None,
    force: bool = False,
    platform_version: str | None = None,
    edt_run: RunFn | None = None,
    edt_discover: Callable[[], EdtCliInfo] | None = None,
) -> ConvertResult:
    """
    Convert configuration source between Designer XML and EDT.

    XML → EDT: ``1cedtcli import`` into staging, replace ``source.path``, set
    ``source.format: edt``.

    EDT → XML: ``1cedtcli export`` into staging, replace ``source.path``, set
    ``source.format: xml``.

    ``source.path`` is kept; when it is the project root, preserve
    ``ROOT_PRESERVE_NAMES`` while swapping format contents.
    """
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    target_fmt = str(to).strip().lower()
    if target_fmt not in CONVERT_TARGETS:
        return _failed(
            started=started,
            root=start_path,
            to_format=target_fmt,
            diagnostics=[
                error(
                    f"Неизвестный целевой формат {to!r}; ожидается edt|xml",
                    code=CODE_CONVERT_DIRTY,
                    source="source",
                    suggestion="Укажите --to=edt или --to=xml",
                )
            ],
        )

    manifest_path = detect_manifest(start_path)
    if manifest_path is None:
        return _failed(
            started=started,
            root=start_path,
            to_format=target_fmt,
            diagnostics=[
                error(
                    f"Файл {MANIFEST_NAME} не найден",
                    code=CODE_PROJECT_MISSING,
                    source="source",
                    suggestion="Выполните 1c-dev init или configuration import",
                )
            ],
        )

    data, load_diags = load_manifest(manifest_path)
    if data is None:
        return _failed(
            started=started,
            root=scope_root_from_manifest(manifest_path),
            to_format=target_fmt,
            diagnostics=list(load_diags)
            or [
                error(
                    "Не удалось прочитать манифест",
                    code=CODE_PROJECT_MISSING,
                    file=str(manifest_path.name),
                    source="source",
                )
            ],
        )

    root = scope_root_from_manifest(manifest_path)
    target, resolve_diags = resolve_config_runtime(
        data,
        config_id=config_id,
        require_runtime=False,
    )
    if target is None:
        return _failed(
            started=started,
            root=root,
            to_format=target_fmt,
            diagnostics=list(resolve_diags),
        )

    source_rel = target.source_rel
    source_dir = (root / source_rel).resolve()
    from_fmt = (target.source_format or "").strip().lower() or None

    if from_fmt == target_fmt:
        if force:
            return ConvertResult(
                status="ok",
                duration=time.perf_counter() - started,
                root=root,
                config_id=target.config_id,
                source_path=source_dir,
                source_rel=source_rel,
                from_format=from_fmt,
                to_format=target_fmt,
                steps=["noop"],
                diagnostics=[],
            )
        return _failed(
            started=started,
            root=root,
            config_id=target.config_id,
            source_path=source_dir,
            source_rel=source_rel,
            from_format=from_fmt,
            to_format=target_fmt,
            diagnostics=[
                error(
                    f"source.format уже {target_fmt!r}",
                    code=CODE_CONVERT_DIRTY,
                    source="source",
                    suggestion="Укажите другой --to или --force для идемпотентного no-op",
                )
            ],
        )

    if from_fmt not in CONVERT_TARGETS:
        return _failed(
            started=started,
            root=root,
            config_id=target.config_id,
            source_path=source_dir,
            source_rel=source_rel,
            from_format=from_fmt,
            to_format=target_fmt,
            diagnostics=[
                error(
                    f"source.format={from_fmt!r}: convert поддерживает xml ↔ edt",
                    code=CODE_CONVERT_DIRTY,
                    source="source",
                    suggestion="Укажите source.format: xml или edt в манифесте",
                )
            ],
        )

    if not source_dir.is_dir():
        return _failed(
            started=started,
            root=root,
            config_id=target.config_id,
            source_path=source_dir,
            source_rel=source_rel,
            from_format=from_fmt,
            to_format=target_fmt,
            diagnostics=[
                error(
                    f"source.path не существует или не каталог: {source_rel}",
                    code=CODE_PROJECT_MISSING,
                    source="source",
                )
            ],
        )

    # Validate current layout before calling 1cedtcli.
    if from_fmt == SOURCE_FORMAT_XML:
        if not (source_dir / "Configuration.xml").is_file():
            return _failed(
                started=started,
                root=root,
                config_id=target.config_id,
                source_path=source_dir,
                source_rel=source_rel,
                from_format=from_fmt,
                to_format=target_fmt,
                diagnostics=[
                    error(
                        f"Нет Configuration.xml в source.path ({source_rel})",
                        code=CODE_CONVERT_DIRTY,
                        source="source",
                        suggestion="Проверьте XML-выгрузку или выполните configuration import",
                    )
                ],
            )
    else:
        checked = validate_edt_source_dir(source_dir)
        if not checked.is_edt:
            return _failed(
                started=started,
                root=root,
                config_id=target.config_id,
                source_path=source_dir,
                source_rel=source_rel,
                from_format=from_fmt,
                to_format=target_fmt,
                diagnostics=[
                    error(
                        checked.message or "Каталог не является EDT-проектом",
                        code=checked.code or CODE_CONVERT_DIRTY,
                        source="edt",
                        suggestion=checked.suggestion,
                    )
                ],
            )

    try:
        info = require_edtcli(
            info=edt_discover() if edt_discover is not None else None,
        )
    except EdtCliError as exc:
        return _failed(
            started=started,
            root=root,
            config_id=target.config_id,
            source_path=source_dir,
            source_rel=source_rel,
            from_format=from_fmt,
            to_format=target_fmt,
            diagnostics=list(exc.diagnostics)
            or [
                error(
                    exc.message,
                    code=exc.code or CODE_EDTCLI_MISSING,
                    source="edt",
                )
            ],
        )
    assert info.path is not None

    steps: list[str] = []
    version = platform_version or _platform_version(data)

    try:
        with tempfile.TemporaryDirectory(prefix="1c-dev-convert-") as tmp:
            staging = Path(tmp) / "staging"
            staging.mkdir(parents=True, exist_ok=True)
            backup = Path(tmp) / "backup"

            if target_fmt == SOURCE_FORMAT_EDT:
                xml_input = Path(tmp) / "xml-input"
                _stage_xml_for_import(source_dir, xml_input, root=root)
                import_configuration(
                    info.path,
                    configuration_files=xml_input,
                    project=staging,
                    platform_version=version,
                    run=edt_run,
                )
                steps.append("edt-import")
            else:
                export_configuration(
                    info.path,
                    project=source_dir,
                    configuration_files=staging,
                    run=edt_run,
                )
                steps.append("edt-export")

            # Safe swap: move current source aside → copy staging → atomic
            # manifest. On any failure after the move, restore from backup so
            # source.path is never left empty and format↔disk never drifts.
            _move_replaceable_into(source_dir, backup, root=root)
            try:
                _copy_tree_into(staging, source_dir)
                steps.append("replace-source")
                _update_source_format(
                    data,
                    config_id=target.config_id,
                    fmt=target_fmt,
                    path_rel=source_rel,
                )
                _write_manifest_atomic(manifest_path, data)
                steps.append("update-manifest")
            except OSError:
                _rollback_source_from_backup(source_dir, backup, root=root)
                raise
    except EdtCliError as exc:
        return _failed(
            started=started,
            root=root,
            config_id=target.config_id,
            source_path=source_dir,
            source_rel=source_rel,
            from_format=from_fmt,
            to_format=target_fmt,
            steps=steps,
            diagnostics=list(exc.diagnostics)
            or [
                error(
                    exc.message,
                    code=exc.code,
                    source="edt",
                )
            ],
        )
    except OSError as exc:
        return _failed(
            started=started,
            root=root,
            config_id=target.config_id,
            source_path=source_dir,
            source_rel=source_rel,
            from_format=from_fmt,
            to_format=target_fmt,
            steps=steps,
            diagnostics=[
                error(
                    f"Не удалось заменить source.path: {exc}",
                    code=CODE_CONVERT_DIRTY,
                    source="source",
                )
            ],
        )

    return ConvertResult(
        status="ok",
        duration=time.perf_counter() - started,
        root=root,
        config_id=target.config_id,
        source_path=source_dir,
        source_rel=source_rel,
        from_format=from_fmt,
        to_format=target_fmt,
        steps=steps,
        diagnostics=[],
    )
