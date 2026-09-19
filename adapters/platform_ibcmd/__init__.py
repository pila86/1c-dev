"""Ibcmd platform adapter: build XML configuration into file IB (ADR-008)."""

from __future__ import annotations

from pathlib import Path

from adapters.platform_ibcmd.client import (
    IbcmdError,
    RunFn,
    apply_config,
    create_infobase,
    import_xml,
    save_cf,
)
from adapters.platform_ibcmd.constants import IB_MARKER

__all__ = [
    "IbcmdError",
    "RunFn",
    "build_with_ibcmd",
    "infobase_exists",
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
    run: RunFn | None = None,
) -> list[str]:
    """
    Create (if needed) → import XML → apply; optionally save .cf.

    Returns list of completed step names: create?, import, apply, save?.
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
        run=run,
    )
    steps.append("import")

    apply_config(ibcmd, db_path=db_path, data_path=data_path, run=run)
    steps.append("apply")

    if cf_path is not None:
        save_cf(
            ibcmd,
            db_path=db_path,
            data_path=data_path,
            cf_path=cf_path,
            run=run,
        )
        steps.append("save")

    return steps
