"""Subprocess wrappers for ibcmd build / import pipelines (ADR-008, ADR-014)."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from adapters.platform_ibcmd.constants import CODE_CHECK_FAILED, CODE_IBCMD_FAILED
from adapters.platform_ibcmd.parse import diagnostics_from_output
from core.diagnostics import Diagnostic


class IbcmdError(Exception):
    """ibcmd step failure with structured diagnostics."""

    def __init__(
        self,
        message: str,
        *,
        code: str = CODE_IBCMD_FAILED,
        diagnostics: list[Diagnostic] | None = None,
        step: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.diagnostics = diagnostics or []
        self.step = step


@dataclass(frozen=True)
class IbcmdRunResult:
    """Raw result of one ibcmd invocation."""

    returncode: int
    stdout: str
    stderr: str
    argv: list[str]


RunFn = Callable[[list[str]], IbcmdRunResult]


def default_run(argv: list[str]) -> IbcmdRunResult:
    """Execute ibcmd and capture output."""
    proc = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        check=False,
    )
    return IbcmdRunResult(
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        argv=list(argv),
    )


def _db_args(db_path: Path, data_path: Path) -> list[str]:
    return [
        f"--db-path={db_path}",
        f"--data={data_path}",
    ]


def _extension_args(extension: str | None) -> list[str]:
    if extension is None:
        return []
    return [f"--extension={extension}"]


def create_infobase(
    ibcmd: Path,
    *,
    db_path: Path,
    data_path: Path,
    run: RunFn | None = None,
) -> IbcmdRunResult:
    """Create a file infobase at db_path."""
    runner = run or default_run
    argv = [
        str(ibcmd),
        "infobase",
        "create",
        *_db_args(db_path, data_path),
    ]
    return _require_ok(runner(argv), step="create")


def import_xml(
    ibcmd: Path,
    *,
    db_path: Path,
    data_path: Path,
    source_dir: Path,
    extension: str | None = None,
    run: RunFn | None = None,
) -> IbcmdRunResult:
    """Import XML configuration dump into the infobase."""
    runner = run or default_run
    argv = [
        str(ibcmd),
        "infobase",
        "config",
        "import",
        *_db_args(db_path, data_path),
        *_extension_args(extension),
        str(source_dir),
    ]
    return _require_ok(runner(argv), step="import")


def apply_config(
    ibcmd: Path,
    *,
    db_path: Path,
    data_path: Path,
    extension: str | None = None,
    run: RunFn | None = None,
) -> IbcmdRunResult:
    """Apply loaded configuration to the database."""
    runner = run or default_run
    argv = [
        str(ibcmd),
        "infobase",
        "config",
        "apply",
        *_db_args(db_path, data_path),
        *_extension_args(extension),
        "--force",
    ]
    return _require_ok(runner(argv), step="apply")


def save_cf(
    ibcmd: Path,
    *,
    db_path: Path,
    data_path: Path,
    cf_path: Path,
    extension: str | None = None,
    run: RunFn | None = None,
) -> IbcmdRunResult:
    """Export database configuration to a .cf / .cfe file."""
    runner = run or default_run
    cf_path.parent.mkdir(parents=True, exist_ok=True)
    argv = [
        str(ibcmd),
        "config",
        "save",
        *_db_args(db_path, data_path),
        *_extension_args(extension),
        "--db",
        str(cf_path),
    ]
    return _require_ok(runner(argv), step="save")


def load_cf(
    ibcmd: Path,
    *,
    db_path: Path,
    data_path: Path,
    cf_path: Path,
    extension: str | None = None,
    run: RunFn | None = None,
) -> IbcmdRunResult:
    """Load configuration from a .cf / .cfe file into the infobase (ADR-014)."""
    runner = run or default_run
    argv = [
        str(ibcmd),
        "infobase",
        "config",
        "load",
        *_db_args(db_path, data_path),
        *_extension_args(extension),
        str(cf_path),
    ]
    return _require_ok(runner(argv), step="load")


def export_xml(
    ibcmd: Path,
    *,
    db_path: Path,
    data_path: Path,
    target_dir: Path,
    extension: str | None = None,
    run: RunFn | None = None,
) -> IbcmdRunResult:
    """Export configuration from the infobase to hierarchical XML (ADR-014)."""
    runner = run or default_run
    target_dir.mkdir(parents=True, exist_ok=True)
    argv = [
        str(ibcmd),
        "infobase",
        "config",
        "export",
        *_db_args(db_path, data_path),
        *_extension_args(extension),
        str(target_dir),
    ]
    return _require_ok(runner(argv), step="export")


def check_config(
    ibcmd: Path,
    *,
    db_path: Path,
    data_path: Path,
    extension: str | None = None,
    run: RunFn | None = None,
) -> IbcmdRunResult:
    """Run platform config check on an existing file infobase (ADR-009)."""
    runner = run or default_run
    argv = [
        str(ibcmd),
        "infobase",
        "config",
        "check",
        *_db_args(db_path, data_path),
        *_extension_args(extension),
    ]
    return _require_ok(runner(argv), step="check", code=CODE_CHECK_FAILED)


@dataclass(frozen=True)
class ExtensionInfo:
    """One row from ``ibcmd extension list``."""

    name: str
    raw: str = ""


def parse_extension_list(stdout: str) -> list[ExtensionInfo]:
    """
    Parse ``ibcmd extension list`` stdout into extension names.

    Platform output is tabular / free-form; take non-empty lines that look like
    names (skip headers containing spaces-only or known Russian/English headers).
    """
    results: list[ExtensionInfo] = []
    header_tokens = {"name", "имя", "extension", "расширение", "version", "версия"}
    for line in stdout.splitlines():
        raw = line.rstrip()
        stripped = raw.strip()
        if not stripped:
            continue
        # First column of a whitespace-separated table
        first = stripped.split()[0]
        if first.lower() in header_tokens:
            continue
        # Skip decorative separators
        if set(stripped) <= {"-", "=", "+", "|", " "}:
            continue
        results.append(ExtensionInfo(name=first, raw=raw))
    return results


def list_extensions(
    ibcmd: Path,
    *,
    db_path: Path,
    data_path: Path,
    run: RunFn | None = None,
) -> tuple[IbcmdRunResult, list[ExtensionInfo]]:
    """List extensions installed in the file infobase (``ibcmd extension list``)."""
    runner = run or default_run
    argv = [
        str(ibcmd),
        "extension",
        "list",
        *_db_args(db_path, data_path),
    ]
    result = _require_ok(runner(argv), step="extension-list")
    return result, parse_extension_list(result.stdout)


def server_config_init(
    ibcmd: Path,
    *,
    out: Path,
    db_path: Path,
    http_port: int,
    name: str,
    http_address: str = "localhost",
    http_base: str = "/",
    run: RunFn | None = None,
) -> IbcmdRunResult:
    """Generate ibsrv YAML via ``ibcmd server config init`` (ADR-025 / spike #84)."""
    runner = run or default_run
    out.parent.mkdir(parents=True, exist_ok=True)
    argv = [
        str(ibcmd),
        "server",
        "config",
        "init",
        f"--out={out}",
        f"--db-path={db_path}",
        f"--http-address={http_address}",
        f"--http-port={http_port}",
        f"--http-base={http_base}",
        f"--name={name}",
    ]
    return _require_ok(runner(argv), step="server-config-init")


def _require_ok(
    result: IbcmdRunResult,
    *,
    step: str,
    code: str | None = None,
) -> IbcmdRunResult:
    if result.returncode == 0:
        return result
    diag_code = code if code is not None else CODE_IBCMD_FAILED
    diags = diagnostics_from_output(
        step=step,
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        code=diag_code,
    )
    raise IbcmdError(
        diags[0]["message"] if diags else f"ibcmd {step} failed",
        code=diag_code,
        diagnostics=diags,
        step=step,
    )
