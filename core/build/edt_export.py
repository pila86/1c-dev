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


def export_edt_to_xml(
    *,
    root: Path,
    config_id: str,
    project_dir: Path,
    edtcli_info: EdtCliInfo | None = None,
    run: RunFn | None = None,
    discover: Callable[[], EdtCliInfo] | None = None,
) -> tuple[Path, list[str], list[Diagnostic]]:
    """
    Validate EDT root, export via 1cedtcli into ``.1c-dev/export/<config-id>/``.

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

    export_dir = prepare_export_dir(export_dir_for_config(root, config_id))
    export_configuration(
        info.path,
        project=project_dir,
        configuration_files=export_dir,
        run=run,
    )
    return export_dir, ["edt-export"], []
