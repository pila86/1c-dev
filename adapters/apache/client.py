"""User-owned Apache httpd: scaffold conf + start/stop (ADR-025 / #94)."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from adapters.apache.constants import CODE_APACHE_FAILED

PID_NAME = "httpd.pid"
CONF_NAME = "httpd.conf"
WWW_DIR_NAME = "www"
LOGS_DIR_NAME = "logs"

# Minimal DSO set for a local publish instance (Apache 2.4).
# log_config / unixd: load when .so exists (ASF source build);
# on Debian/Ubuntu they are often built-in — absent .so is OK.
_CORE_MODULES = (
    ("mpm_event_module", "mod_mpm_event.so"),
    ("authz_core_module", "mod_authz_core.so"),
    ("unixd_module", "mod_unixd.so"),
    ("log_config_module", "mod_log_config.so"),
    ("alias_module", "mod_alias.so"),
    ("dir_module", "mod_dir.so"),
    ("mime_module", "mod_mime.so"),
)

_MIME_TYPES_CANDIDATES = (
    Path("/etc/mime.types"),
    Path("/etc/apache2/mime.types"),
)


def _resolve_mime_types(*, modules_dir: Path | None = None) -> Path | None:
    if modules_dir is not None:
        bundled = modules_dir.parent / "conf" / "mime.types"
        if bundled.is_file():
            return bundled.resolve()
    for candidate in _MIME_TYPES_CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


@dataclass(frozen=True)
class ApacheRunResult:
    """Raw result of one httpd invocation."""

    returncode: int
    stdout: str
    stderr: str
    argv: list[str]


RunFn = Callable[[list[str]], ApacheRunResult]


def default_run(argv: list[str]) -> ApacheRunResult:
    """Execute httpd and capture output."""
    proc = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        check=False,
    )
    return ApacheRunResult(
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        argv=list(argv),
    )


def _load_module_lines(modules_dir: Path, *, ws_module: Path | None) -> list[str]:
    lines: list[str] = []
    for name, filename in _CORE_MODULES:
        path = modules_dir / filename
        if path.is_file():
            lines.append(f'LoadModule {name} "{path}"')
    # Debian/Ubuntu often uses mpm_prefork instead of event.
    if not any("mpm_" in line for line in lines):
        for name, filename in (
            ("mpm_prefork_module", "mod_mpm_prefork.so"),
            ("mpm_worker_module", "mod_mpm_worker.so"),
        ):
            path = modules_dir / filename
            if path.is_file():
                lines.append(f'LoadModule {name} "{path}"')
                break
    if ws_module is not None and ws_module.is_file():
        lines.append(f'LoadModule _1cws_module "{ws_module.resolve()}"')
    return lines


def scaffold_httpd_conf(
    conf_path: Path,
    *,
    server_root: Path,
    port: int,
    modules_dir: Path,
    ws_module: Path | None,
    address: str = "127.0.0.1",
) -> Path:
    """
    Write a minimal user-owned ``httpd.conf``.

    Publication Alias/Directory blocks are appended by
    ``adapters.webinst.materialize_publication``.
    ``server_root`` is ServerRoot / PidFile parent (``.1c-dev/publish/<profile>``).
    """
    server_root = server_root.resolve()
    www = server_root / WWW_DIR_NAME
    logs = server_root / LOGS_DIR_NAME
    www.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    conf_path = conf_path.resolve()
    conf_path.parent.mkdir(parents=True, exist_ok=True)
    pid_file = server_root / PID_NAME
    modules = _load_module_lines(modules_dir, ws_module=ws_module)
    # LoadModule must precede LogFormat/CustomLog/TypesConfig.
    body_lines = [
        f'ServerRoot "{server_root}"',
        f"Listen {address}:{port}",
        "ServerName localhost",
        f'PidFile "{pid_file}"',
        f'ErrorLog "{logs / "error.log"}"',
        *modules,
        'LogFormat "%h %l %u %t \\"%r\\" %>s %b" common',
        f'CustomLog "{logs / "access.log"}" common',
        f'DocumentRoot "{www}"',
    ]
    mime_types = _resolve_mime_types(modules_dir=modules_dir)
    if mime_types is not None and any("mime_module" in line for line in modules):
        body_lines.append(f'TypesConfig "{mime_types}"')
    body_lines.extend(
        [
            "",
            "# 1c-dev: publication blocks appended below",
            "",
        ]
    )
    conf_path.write_text("\n".join(body_lines), encoding="utf-8")
    return conf_path


def start_httpd(
    httpd: Path,
    *,
    conf: Path,
    server_root: Path,
    run: RunFn | None = None,
) -> ApacheRunResult:
    """Start httpd with user-owned conf (``-f`` / ``-d``)."""
    runner = run or default_run
    argv = [
        str(httpd),
        "-f",
        str(conf.resolve()),
        "-d",
        str(server_root.resolve()),
    ]
    return runner(argv)


def read_pid(profile_dir: Path) -> int | None:
    """Read PID from ``httpd.pid``; return None if missing/invalid."""
    path = profile_dir / PID_NAME
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


def clear_pid(profile_dir: Path) -> None:
    """Remove stale ``httpd.pid`` if present."""
    path = profile_dir / PID_NAME
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def find_ws_module(platform_bin_dir: Path | None) -> Path | None:
    """Locate ``wsap24.so`` / ``wsap24.dll`` next to platform binaries."""
    if platform_bin_dir is None:
        return None
    for name in ("wsap24.so", "wsap24.dll", "wsap22.so", "wsap22.dll"):
        candidate = platform_bin_dir / name
        if candidate.is_file():
            return candidate.resolve()
    return None


class ApacheError(Exception):
    """Apache step failure."""

    def __init__(self, message: str, *, code: str = CODE_APACHE_FAILED) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
