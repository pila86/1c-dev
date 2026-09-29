"""Subprocess wrappers for webinst publish/delete (ADR-025 / #94)."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from adapters.webinst.constants import CODE_WEBINST_FAILED

_SERVER_FLAGS = {
    "apache24": "-apache24",
    "apache22": "-apache22",
    "apache2": "-apache2",
    "iis": "-iis",
}

_VRD_IB_RE = re.compile(r'\bib\s*=\s*"([^"]*)"', re.IGNORECASE)


@dataclass(frozen=True)
class WebinstRunResult:
    """Raw result of one webinst invocation."""

    returncode: int
    stdout: str
    stderr: str
    argv: list[str]


RunFn = Callable[[list[str]], WebinstRunResult]


def default_run(argv: list[str]) -> WebinstRunResult:
    """Execute webinst and capture output."""
    proc = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        check=False,
    )
    return WebinstRunResult(
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        argv=list(argv),
    )


def server_flag(server: str) -> str:
    """Map profile.server to webinst flag (default ``-apache24``)."""
    key = (server or "apache24").strip().lower()
    return _SERVER_FLAGS.get(key, "-apache24")


def file_conn_str(db_path: Path) -> str:
    """Build file IB connection string for ``-connStr``."""
    return f'File="{db_path.resolve()}";'


def build_url(*, address: str = "127.0.0.1", port: int, wsdir: str) -> str:
    """Build publish URL ``http://{address}:{port}/{wsdir}``."""
    base = wsdir.strip().strip("/")
    return f"http://{address}:{port}/{base}"


def publish(
    webinst: Path,
    *,
    server: str,
    wsdir: str,
    www_dir: Path,
    db_path: Path,
    conf_path: Path,
    run: RunFn | None = None,
) -> WebinstRunResult:
    """Publish file IB via webinst into user-owned Apache conf."""
    runner = run or default_run
    www_dir.mkdir(parents=True, exist_ok=True)
    argv = [
        str(webinst),
        server_flag(server),
        "-wsdir",
        wsdir,
        "-dir",
        str(www_dir.resolve()),
        "-connStr",
        file_conn_str(db_path),
        "-confPath",
        str(conf_path.resolve()),
    ]
    return runner(argv)


def delete(
    webinst: Path,
    *,
    server: str,
    wsdir: str,
    conf_path: Path,
    run: RunFn | None = None,
) -> WebinstRunResult:
    """Remove publication via ``webinst -delete``."""
    runner = run or default_run
    argv = [
        str(webinst),
        "-delete",
        server_flag(server),
        "-wsdir",
        wsdir,
        "-confPath",
        str(conf_path.resolve()),
    ]
    return runner(argv)


def vrd_path(www_dir: Path) -> Path:
    return www_dir / "default.vrd"


def _virt_path(wsdir: str) -> str:
    return "/" + wsdir.strip().strip("/")


def _marker_begin(wsdir: str) -> str:
    return f"# 1c-dev publication begin:{wsdir.strip().strip('/')}"


def _marker_end(wsdir: str) -> str:
    return f"# 1c-dev publication end:{wsdir.strip().strip('/')}"


def write_default_vrd(www_dir: Path, *, wsdir: str, db_path: Path) -> Path:
    """
    Write ``default.vrd`` compatible with webinst / wsap24 (no root required).

    Shape matches platform ``webinst -apache24`` output, plus
    ``httpServices publishByDefault`` / ``publishExtensionsByDefault`` so all
    HTTP services (включая расширения) доступны без ручного VRD.
    """
    www_dir.mkdir(parents=True, exist_ok=True)
    path = vrd_path(www_dir)
    base = _virt_path(wsdir)
    ib_attr = file_conn_str(db_path).replace('"', "&quot;")
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<point xmlns="http://v8.1c.ru/8.2/virtual-resource-system"\n'
        '\txmlns:xs="http://www.w3.org/2001/XMLSchema"\n'
        '\txmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n'
        f'\tbase="{base}"\n'
        f'\tib="{ib_attr}">\n'
        '\t<ws pointEnableCommon="true"/>\n'
        '\t<httpServices publishByDefault="true"\n'
        '\t\tpublishExtensionsByDefault="true"/>\n'
        '\t<standardOdata enable="false"\n'
        '\t\treuseSessions="autouse"\n'
        '\t\tsessionMaxAge="20"\n'
        '\t\tpoolSize="10"\n'
        '\t\tpoolTimeout="5"/>\n'
        '\t<analytics enable="true"/>\n'
        "</point>\n"
    )
    path.write_text(body, encoding="utf-8")
    return path


def _strip_publication_blocks(text: str, wsdir: str) -> str:
    """Remove our marked block and legacy webinst ``# 1c publication`` for wsdir."""
    begin = _marker_begin(wsdir)
    end = _marker_end(wsdir)
    while True:
        start = text.find(begin)
        if start < 0:
            break
        stop = text.find(end, start)
        if stop < 0:
            text = text[:start]
            break
        text = text[:start] + text[stop + len(end) :]

    # Legacy webinst block: from "# 1c publication" through matching Directory
    virt = _virt_path(wsdir)
    needle = f'Alias "{virt}"'
    while True:
        alias_at = text.find(needle)
        if alias_at < 0:
            break
        # Prefer to include preceding "# 1c publication" comment if present
        block_start = text.rfind("\n", 0, alias_at)
        header = text.rfind("# 1c publication", 0, alias_at)
        if header >= 0 and (block_start < 0 or header > block_start - 40):
            line_start = text.rfind("\n", 0, header)
            start = 0 if line_start < 0 else line_start + 1
        else:
            start = 0 if block_start < 0 else block_start + 1
        dir_close = text.find("</Directory>", alias_at)
        if dir_close < 0:
            text = text[:start]
            break
        end_pos = dir_close + len("</Directory>")
        if end_pos < len(text) and text[end_pos] == "\r":
            end_pos += 1
        if end_pos < len(text) and text[end_pos] == "\n":
            end_pos += 1
        text = text[:start] + text[end_pos:]

    return text.rstrip() + ("\n" if text.strip() else "")


def apply_httpd_publication(
    conf_path: Path,
    *,
    wsdir: str,
    www_dir: Path,
) -> None:
    """Idempotently append Alias/Directory block for wsdir into httpd.conf."""
    www = www_dir.resolve()
    vrd = (www / "default.vrd").resolve()
    virt = _virt_path(wsdir)
    block = "\n".join(
        [
            _marker_begin(wsdir),
            f'Alias "{virt}" "{www}/"',
            f'<Directory "{www}/">',
            "    AllowOverride All",
            "    Options None",
            "    Require all granted",
            "    SetHandler 1c-application",
            f'    ManagedApplicationDescriptor "{vrd}"',
            "</Directory>",
            _marker_end(wsdir),
            "",
        ]
    )
    existing = ""
    if conf_path.is_file():
        existing = conf_path.read_text(encoding="utf-8")
    cleaned = _strip_publication_blocks(existing, wsdir)
    if cleaned and not cleaned.endswith("\n"):
        cleaned += "\n"
    conf_path.parent.mkdir(parents=True, exist_ok=True)
    conf_path.write_text(cleaned + "\n" + block, encoding="utf-8")


def remove_httpd_publication(
    conf_path: Path,
    *,
    wsdir: str,
    www_dir: Path | None = None,
) -> None:
    """Remove Alias/Directory block and optional default.vrd."""
    if conf_path.is_file():
        text = conf_path.read_text(encoding="utf-8")
        conf_path.write_text(_strip_publication_blocks(text, wsdir), encoding="utf-8")
    if www_dir is not None:
        path = vrd_path(www_dir)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def materialize_publication(
    *,
    conf_path: Path,
    www_dir: Path,
    wsdir: str,
    db_path: Path,
) -> None:
    """Write default.vrd + httpd Alias/Directory without calling webinst binary."""
    write_default_vrd(www_dir, wsdir=wsdir, db_path=db_path)
    apply_httpd_publication(conf_path, wsdir=wsdir, www_dir=www_dir)


def vrd_matches_ib(www_dir: Path, db_path: Path) -> bool:
    """True if ``default.vrd`` exists and points at the same file IB path."""
    path = vrd_path(www_dir)
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    match = _VRD_IB_RE.search(text)
    if match is None:
        # Fallback: substring check for File= path
        needle = str(db_path.resolve())
        return needle in text
    ib = match.group(1)
    needle = str(db_path.resolve())
    return needle in ib or ib.replace("\\", "/") == needle.replace("\\", "/")


class WebinstError(Exception):
    """webinst step failure."""

    def __init__(self, message: str, *, code: str = CODE_WEBINST_FAILED) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
