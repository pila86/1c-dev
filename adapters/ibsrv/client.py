"""Subprocess wrappers for ibsrv daemon lifecycle (ADR-025 / spike #84)."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from adapters.ibsrv.constants import CODE_IBSRV_FAILED

LOCK_PID_NAME = "lock.pid"


@dataclass(frozen=True)
class IbsrvRunResult:
    """Raw result of one ibsrv invocation."""

    returncode: int
    stdout: str
    stderr: str
    argv: list[str]


RunFn = Callable[[list[str]], IbsrvRunResult]


def default_run(argv: list[str]) -> IbsrvRunResult:
    """Execute ibsrv and capture output."""
    proc = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        check=False,
    )
    return IbsrvRunResult(
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        argv=list(argv),
    )


def start_daemon(
    ibsrv: Path,
    *,
    config: Path,
    data: Path,
    run: RunFn | None = None,
) -> IbsrvRunResult:
    """
    Start ibsrv in daemon mode (HTTP-only local publish).

    Always passes ``--disable-direct-gate`` / ``--disable-ssh-gate`` so default
    ports 1541/1543 do not collide with a local cluster.
    """
    runner = run or default_run
    data.mkdir(parents=True, exist_ok=True)
    argv = [
        str(ibsrv),
        "--daemon",
        f"--config={config}",
        f"--data={data}",
        "--disable-direct-gate",
        "--disable-ssh-gate",
    ]
    return runner(argv)


def read_lock_pid(data_dir: Path) -> int | None:
    """Read PID from ``<data>/lock.pid``; return None if missing/invalid."""
    path = data_dir / LOCK_PID_NAME
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    try:
        pid = int(text.split()[0])
    except (ValueError, IndexError):
        return None
    return pid if pid > 0 else None


def clear_lock_pid(data_dir: Path) -> None:
    """Remove stale ``lock.pid`` if present."""
    path = data_dir / LOCK_PID_NAME
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def parse_server_config(config_path: Path) -> dict[str, Any]:
    """Load ibsrv YAML into a dict (empty dict if missing/invalid)."""
    if not config_path.is_file():
        return {}
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return raw if isinstance(raw, dict) else {}


def build_url(config: dict[str, Any]) -> str | None:
    """
    Build publish URL from ibsrv YAML.

    ``http://{server.address}:{server.port}{http.base}``
    """
    server = config.get("server")
    if not isinstance(server, dict):
        return None
    address = server.get("address")
    port = server.get("port")
    if not isinstance(address, str) or not address:
        return None
    if not isinstance(port, int):
        try:
            port = int(port)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
    http = config.get("http")
    base = "/"
    if isinstance(http, dict):
        raw_base = http.get("base")
        if isinstance(raw_base, str) and raw_base:
            base = raw_base if raw_base.startswith("/") else f"/{raw_base}"
    if not base.startswith("/"):
        base = f"/{base}"
    return f"http://{address}:{port}{base}"


class IbsrvError(Exception):
    """ibsrv step failure."""

    def __init__(self, message: str, *, code: str = CODE_IBSRV_FAILED) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
