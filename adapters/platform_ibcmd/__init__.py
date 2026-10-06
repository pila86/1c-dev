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
    update_extension_properties,
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
    "import_cfe_with_ibcmd",
    "infobase_exists",
    "list_extensions",
    "load_cf",
    "load_cf_with_ibcmd",
    "server_config_init",
    "update_extension_properties",
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
    extensions: list[tuple[str, Path]] | list[tuple[str, Path, str]] | None = None,
    run: RunFn | None = None,
) -> list[str]:
    """
    Create (if needed) → import XML → apply; then each nested extension; optionally save .cf.

    primary_extension: when set, the main source is an extension (standalone project).
    extensions: nested (ibcmd_name, path[, kind]) loaded after the main configuration.
      kind defaults to \"xml\"; \"cfe\" uses config load --extension (#95).
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

    for item in extensions or []:
        if len(item) == 3:
            ext_name, ext_path, kind = item[0], item[1], item[2]
        else:
            ext_name, ext_path = item[0], item[1]
            kind = "xml"
        if kind == "cfe":
            load_cf(
                ibcmd,
                db_path=db_path,
                data_path=data_path,
                cf_path=ext_path,
                extension=ext_name,
                run=run,
            )
            steps.append(f"load:{ext_name}")
        else:
            import_xml(
                ibcmd,
                db_path=db_path,
                data_path=data_path,
                source_dir=ext_path,
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
    extension: str | None = None,
    run: RunFn | None = None,
) -> list[str]:
    """
    Create (if needed) → load .cf/.cfe → apply (no export; ADR-015 / #95).

    extension: when set, load/apply use --extension (`.cfe` into IB).
    Returns list of completed step names: create?, load|load:Name, apply|apply:Name.
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
        extension=extension,
        run=run,
    )
    steps.append(f"load:{extension}" if extension else "load")

    apply_config(
        ibcmd,
        db_path=db_path,
        data_path=data_path,
        extension=extension,
        run=run,
    )
    steps.append(f"apply:{extension}" if extension else "apply")

    return steps


def import_cfe_with_ibcmd(
    ibcmd: Path,
    *,
    db_path: Path,
    data_path: Path,
    cfe_path: Path,
    source_dir: Path,
    extension: str,
    run: RunFn | None = None,
) -> list[str]:
    """
    Create (if needed) → load .cfe --extension → apply → export XML (#95).

    On 8.3.25 ``config export --file=.cfe`` without IB does not work; use load/export.
    Returns: create?, load:Name, apply:Name, export.
    """
    steps = load_cf_with_ibcmd(
        ibcmd,
        db_path=db_path,
        data_path=data_path,
        cf_path=cfe_path,
        extension=extension,
        run=run,
    )
    export_xml(
        ibcmd,
        db_path=db_path,
        data_path=data_path,
        target_dir=source_dir,
        extension=extension,
        run=run,
    )
    steps.append("export")
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
