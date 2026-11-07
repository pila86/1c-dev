"""EDT → Designer XML staging for build (ADR-032 / #155)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from adapters.edtcli import (
    EdtCliError,
    EdtCliInfo,
    RunFn,
    export_configuration,
    prepare_export_dir,
    require_edtcli,
)
from adapters.source.edt.detect import validate_edt_source_dir
from core.diagnostics import Diagnostic, error
from core.project.constants import HOME_EXPORT_DIR_NAME


def export_dir_for_config(root: Path, config_id: str) -> Path:
    """``.1c-dev/export/<config-id>/`` under project scope root."""
    return (root / HOME_EXPORT_DIR_NAME / config_id).resolve()


def export_dir_for_extension(root: Path, config_id: str, extension_id: str) -> Path:
    """``.1c-dev/export/<config-id>/ext/<extension-id>/`` (nested EDT extension)."""
    return (root / HOME_EXPORT_DIR_NAME / config_id / "ext" / extension_id).resolve()


def export_edt_to_xml(
    *,
    root: Path,
    config_id: str,
    project_dir: Path,
    extension_id: str | None = None,
    step_name: str = "edt-export",
    edtcli_info: EdtCliInfo | None = None,
    run: RunFn | None = None,
    discover: Callable[[], EdtCliInfo] | None = None,
) -> tuple[Path, list[str], list[Diagnostic]]:
    """
    Validate EDT root, export via 1cedtcli into staging under ``.1c-dev/export/``.

    Default staging: ``.1c-dev/export/<config-id>/``.
    With ``extension_id``: ``.1c-dev/export/<config-id>/ext/<extension-id>/``
    (must run after main-config export so ``prepare_export_dir`` on the config
    root does not wipe nested ``ext/``).

    Returns ``(export_dir, steps, diagnostics)``. On failure raises ``EdtCliError``.
    """
    checked = validate_edt_source_dir(project_dir)
    if not checked.is_edt:
        raise EdtCliError(
            checked.message or "Каталог не является EDT-проектом",
            code=checked.code or "1CS003",
            diagnostics=[
                error(
                    checked.message or "Каталог не является EDT-проектом",
                    code=checked.code or "1CS003",
                    source="edt",
                    suggestion=checked.suggestion,
                )
            ],
        )

    resolved = edtcli_info if edtcli_info is not None else (
        discover() if discover is not None else None
    )
    info = require_edtcli(info=resolved)
    assert info.path is not None

    if extension_id is not None:
        target = export_dir_for_extension(root, config_id, extension_id)
    else:
        target = export_dir_for_config(root, config_id)
    export_dir = prepare_export_dir(target)
    export_configuration(
        info.path,
        project=project_dir,
        configuration_files=export_dir,
        run=run,
    )
    return export_dir, [step_name], []
