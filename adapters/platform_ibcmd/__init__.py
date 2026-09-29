"""Ibcmd platform adapter: build, check, import from .cf (ADR-008, ADR-009, ADR-014)."""

from __future__ import annotations

from pathlib import Path

from adapters.platform_ibcmd.client import (
    ExtensionInfo,
    IbcmdError,
    RunFn,
    apply_config,
    check_config,
    create_infobase,
    export_xml,
    import_xml,
    list_extensions,
    load_cf,
    save_cf,
    server_config_init,
)
from adapters.platform_ibcmd.constants import IB_MARKER

__all__ = [
    "ExtensionInfo",
    "IbcmdError",
    "RunFn",
    "build_with_ibcmd",
    "check_config",
    "export_xml",
    "import_cf_with_ibcmd",
    "infobase_exists",
    "list_extensions",
    "load_cf",
    "load_cf_with_ibcmd",
    "server_config_init",
]


def infobase_exists(db_path: Path) -> bool:
    """True if file IB marker is present under db_path."""
    return (db_path / IB_MARKER).is_file()


def build_with_ibcmd(
    ibcmd: Path,
    *,
    db_path: Path,
    data_path: Path,
    source_dir: Path,
    cf_path: Path | None = None,
    primary_extension: str | None = None,
    extensions: list[tuple[str, Path]] | None = None,
    run: RunFn | None = None,
) -> list[str]:
    """
    Create (if needed) → import XML → apply; then each nested extension; optionally save .cf.

    primary_extension: when set, the main source is an extension (standalone project).
    extensions: nested (ibcmd_name, xml_source_dir) loaded after the main configuration.
    Returns list of completed step names: create?, import|import:Name, apply|apply:Name, …, save?.
    """
    steps: list[str] = []
    db_path.mkdir(parents=True, exist_ok=True)
    data_path.mkdir(parents=True, exist_ok=True)

    if not infobase_exists(db_path):
        create_infobase(ibcmd, db_path=db_path, data_path=data_path, run=run)
        steps.append("create")

    import_xml(
        ibcmd,
        db_path=db_path,
        data_path=data_path,
        source_dir=source_dir,
        extension=primary_extension,
        run=run,
    )
    steps.append(f"import:{primary_extension}" if primary_extension else "import")

    apply_config(
        ibcmd,
        db_path=db_path,
        data_path=data_path,
        extension=primary_extension,
        run=run,
    )
    steps.append(f"apply:{primary_extension}" if primary_extension else "apply")

    for ext_name, ext_dir in extensions or []:
        import_xml(
            ibcmd,
            db_path=db_path,
            data_path=data_path,
            source_dir=ext_dir,
            extension=ext_name,
            run=run,
        )
        steps.append(f"import:{ext_name}")
        apply_config(
            ibcmd,
            db_path=db_path,
            data_path=data_path,
            extension=ext_name,
            run=run,
        )
        steps.append(f"apply:{ext_name}")

    if cf_path is not None:
        save_cf(
            ibcmd,
            db_path=db_path,
            data_path=data_path,
            cf_path=cf_path,
            extension=primary_extension,
            run=run,
        )
        steps.append("save")

    return steps


def load_cf_with_ibcmd(
    ibcmd: Path,
    *,
    db_path: Path,
    data_path: Path,
    cf_path: Path,
    run: RunFn | None = None,
) -> list[str]:
    """
    Create (if needed) → load .cf → apply (no export; ADR-015 runtime.load).

    Returns list of completed step names: create?, load, apply.
    """
    steps: list[str] = []
    db_path.mkdir(parents=True, exist_ok=True)
    data_path.mkdir(parents=True, exist_ok=True)

    if not infobase_exists(db_path):
        create_infobase(ibcmd, db_path=db_path, data_path=data_path, run=run)
        steps.append("create")

    load_cf(
        ibcmd,
        db_path=db_path,
        data_path=data_path,
        cf_path=cf_path,
        run=run,
    )
    steps.append("load")

    apply_config(ibcmd, db_path=db_path, data_path=data_path, run=run)
    steps.append("apply")

    return steps


def import_cf_with_ibcmd(
    ibcmd: Path,
    *,
    db_path: Path,
    data_path: Path,
    cf_path: Path,
    source_dir: Path,
    run: RunFn | None = None,
) -> list[str]:
    """
    Create (if needed) → load .cf → apply → export XML (ADR-014).

    Returns list of completed step names: create?, load, apply, export.
    """
    steps = load_cf_with_ibcmd(
        ibcmd,
        db_path=db_path,
        data_path=data_path,
        cf_path=cf_path,
        run=run,
    )

    export_xml(
        ibcmd,
        db_path=db_path,
        data_path=data_path,
        target_dir=source_dir,
        run=run,
    )
    steps.append("export")

    return steps
