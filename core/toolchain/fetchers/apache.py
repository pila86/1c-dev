"""Install user-owned Apache httpd home into tools cache (ADR-013 / #94)."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from core.diagnostics import Diagnostic, warning
from core.toolchain.manifest import ComponentSpec
from core.toolchain.progress import ProgressFn, noop_progress

META_NAME = ".1c-dev-apache.json"
STABLE_NAME = "apache"
DEFAULT_PIN = "2.4.68"

DEFAULT_BUILD = {
    "httpd": "https://downloads.apache.org/httpd/httpd-2.4.68.tar.gz",
    "apr": "https://downloads.apache.org/apr/apr-1.7.6.tar.gz",
    "apr_util": "https://downloads.apache.org/apr/apr-util-1.6.5.tar.gz",
}


def apache_meta_path(home: Path) -> Path:
    return home / META_NAME


def read_modules_dir(home: Path) -> Path | None:
    """Return modules directory for an apache home (meta or ``modules/``)."""
    modules = home / "modules"
    if modules.is_dir():
        return modules.resolve()
    meta = apache_meta_path(home)
    if meta.is_file():
        try:
            raw = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if isinstance(raw, dict):
            path_raw = raw.get("modules_dir")
            if isinstance(path_raw, str) and path_raw.strip():
                path = Path(path_raw).expanduser()
                if path.is_dir():
                    return path.resolve()
    return None


def httpd_binary(home: Path) -> Path | None:
    """Resolve ``bin/httpd`` (or ``httpd.exe`` / wrapper) under home."""
    bin_dir = home / "bin"
    for name in ("httpd", "httpd.exe", "apache2", "apache2.exe"):
        candidate = bin_dir / name
        if candidate.is_file() or candidate.is_symlink():
            return candidate.resolve()
    return None


def _platform_key() -> str:
    system = sys.platform
    machine = platform.machine().lower()
    if system == "linux":
        if machine in {"x86_64", "amd64"}:
            return "linux_x86_64"
        if machine in {"aarch64", "arm64"}:
            return "linux_aarch64"
    if system == "darwin":
        if machine in {"arm64", "aarch64"}:
            return "darwin_arm64"
        return "darwin_x86_64"
    if system == "win32":
        return "windows_amd64"
    return f"{system}_{machine}"


def _module_files(modules: Path) -> list[Path]:
    if not modules.is_dir():
        return []
    found: list[Path] = []
    for pattern in ("*.so", "*.dll"):
        found.extend(modules.glob(pattern))
    return found


def is_bundled_apache_home(path: Path) -> bool:
    """True when home has httpd + local ``modules/`` (not a thin system wrapper)."""
    if httpd_binary(path) is None:
        return False
    modules = path / "modules"
    return bool(_module_files(modules))


def _looks_like_apache_home(path: Path) -> bool:
    """Accept bundled homes or env overrides with external modules via meta."""
    if is_bundled_apache_home(path):
        return True
    if httpd_binary(path) is None:
        return False
    modules = read_modules_dir(path)
    return modules is not None and bool(_module_files(modules))


def _archive_urls(spec: ComponentSpec) -> list[str]:
    source = spec.source or {}
    key = _platform_key()
    urls = source.get("urls")
    out: list[str] = []
    if isinstance(urls, dict):
        raw = urls.get(key)
        if isinstance(raw, str) and raw.strip():
            out.append(raw.strip())
        elif isinstance(raw, list):
            out.extend(str(item).strip() for item in raw if str(item).strip())
    raw_url = source.get("url")
    if isinstance(raw_url, str) and raw_url.strip():
        out.append(raw_url.strip())
    return out


def _build_urls(spec: ComponentSpec) -> dict[str, str] | None:
    source = spec.source or {}
    build = source.get("build")
    if not isinstance(build, dict):
        if sys.platform == "win32":
            return None
        return dict(DEFAULT_BUILD)
    httpd = str(build.get("httpd") or "").strip()
    apr = str(build.get("apr") or "").strip()
    apr_util = str(build.get("apr_util") or "").strip()
    if httpd and apr and apr_util:
        return {"httpd": httpd, "apr": apr, "apr_util": apr_util}
    return None


def _write_meta(
    home: Path,
    *,
    modules_dir: Path,
    binary: Path,
    extra: dict[str, str] | None = None,
) -> None:
    payload: dict[str, str] = {
        "modules_dir": str(modules_dir),
        "binary": str(binary),
        "platform": _platform_key(),
    }
    if extra:
        payload.update(extra)
    apache_meta_path(home).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _publish_home(tools_dir: Path, *, pin: str, unpacked: Path) -> Path:
    pinned = tools_dir / f"{STABLE_NAME}-{pin}"
    stable = tools_dir / STABLE_NAME
    if pinned.exists():
        shutil.rmtree(pinned)
    shutil.copytree(unpacked, pinned, symlinks=True)
    if stable.exists():
        shutil.rmtree(stable)
    shutil.copytree(pinned, stable, symlinks=True)
    for home in (stable, pinned):
        httpd = httpd_binary(home)
        modules = home / "modules"
        if httpd is not None and sys.platform != "win32":
            httpd.chmod(httpd.stat().st_mode | 0o111)
        if httpd is not None and modules.is_dir():
            _write_meta(
                home,
                modules_dir=modules,
                binary=httpd,
                extra={"source": "archive", "pin": pin},
            )
    return stable.resolve()


def _find_unpacked_home(root: Path) -> Path | None:
    if is_bundled_apache_home(root):
        return root
    for child in sorted(root.iterdir()):
        if child.is_dir() and is_bundled_apache_home(child):
            return child
        nested = child / "Apache24"
        if nested.is_dir() and is_bundled_apache_home(nested):
            return nested
    return None


def _unpack_archive(archive: Path, dest: Path) -> Path | None:
    dest.mkdir(parents=True, exist_ok=True)
    if archive.suffix == ".zip" or archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest)
    else:
        with tarfile.open(archive) as tf:
            tf.extractall(dest)
    return _find_unpacked_home(dest)


def _download_and_install(
    *,
    url: str,
    tools_dir: Path,
    pin: str,
    report: ProgressFn,
) -> Path | None:
    report("→ apache: download archive…")
    tools_dir.mkdir(parents=True, exist_ok=True)
    suffix = ".zip" if url.rstrip("/").endswith(".zip") else ".tar.gz"
    with tempfile.NamedTemporaryFile(
        prefix="apache-",
        suffix=suffix,
        delete=False,
        dir=str(tools_dir),
    ) as tmp:
        tmp_path = Path(tmp.name)
    extract_root = tools_dir / f".apache-extract-{os.getpid()}"
    try:
        urllib.request.urlretrieve(url, tmp_path)  # noqa: S310 — pinned manifest URL
        if extract_root.exists():
            shutil.rmtree(extract_root)
        unpacked = _unpack_archive(tmp_path, extract_root)
        if unpacked is None:
            return None
        return _publish_home(tools_dir, pin=pin, unpacked=unpacked)
    finally:
        tmp_path.unlink(missing_ok=True)
        if extract_root.exists():
            shutil.rmtree(extract_root, ignore_errors=True)


def _tarball_root_name(archive: Path) -> str:
    with tarfile.open(archive) as tf:
        names = [m.name.split("/", 1)[0] for m in tf.getmembers() if m.name]
    if not names:
        raise OSError(f"пустой архив: {archive}")
    return names[0]


def _run(cmd: list[str], *, cwd: Path, report: ProgressFn) -> None:
    report(f"→ apache: {' '.join(cmd[:2])}…")
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-20:]
        detail = "\n".join(tail) if tail else f"exit {proc.returncode}"
        raise OSError(detail)


def _jobs() -> str:
    cpu = os.cpu_count() or 2
    return str(max(1, cpu))


def _build_from_source(
    *,
    urls: dict[str, str],
    tools_dir: Path,
    pin: str,
    report: ProgressFn,
) -> Path:
    """Download ASF httpd+apr+apr-util and install into tools/apache."""
    for tool in ("gcc", "make", "tar"):
        if shutil.which(tool) is None:
            raise OSError(f"нужен {tool} в PATH для сборки Apache")

    tools_dir.mkdir(parents=True, exist_ok=True)
    build_root = tools_dir / f".apache-build-{os.getpid()}"
    if build_root.exists():
        shutil.rmtree(build_root)
    build_root.mkdir(parents=True)
    prefix = build_root / "prefix"
    prefix.mkdir()

    try:
        report("→ apache: download ASF sources…")
        archives: dict[str, Path] = {}
        for key, url in urls.items():
            dest = build_root / f"{key}.tar.gz"
            urllib.request.urlretrieve(url, dest)  # noqa: S310 — pinned manifest URL
            archives[key] = dest

        report("→ apache: unpack…")
        extracted: dict[str, Path] = {}
        for key, archive in archives.items():
            with tarfile.open(archive) as tf:
                tf.extractall(build_root)
            root_name = _tarball_root_name(archive)
            root = build_root / root_name
            if not root.is_dir():
                raise OSError(f"не найден каталог {root_name} после распаковки {key}")
            extracted[key] = root

        httpd_src = extracted["httpd"]
        srclib = httpd_src / "srclib"
        apr_dest = srclib / "apr"
        apu_dest = srclib / "apr-util"
        if apr_dest.exists():
            shutil.rmtree(apr_dest)
        if apu_dest.exists():
            shutil.rmtree(apu_dest)
        shutil.move(str(extracted["apr"]), str(apr_dest))
        shutil.move(str(extracted["apr_util"]), str(apu_dest))

        _run(
            [
                "./configure",
                f"--prefix={prefix}",
                "--enable-mpms-shared=all",
                "--enable-mods-shared=most",
                "--with-included-apr",
            ],
            cwd=httpd_src,
            report=report,
        )
        _run(["make", f"-j{_jobs()}"], cwd=httpd_src, report=report)
        _run(["make", "install"], cwd=httpd_src, report=report)

        if not is_bundled_apache_home(prefix):
            raise OSError("make install не создал bin/httpd + modules/")

        httpd = httpd_binary(prefix)
        modules = prefix / "modules"
        assert httpd is not None
        _write_meta(
            prefix,
            modules_dir=modules,
            binary=httpd,
            extra={"source": "asf-source", "pin": pin},
        )
        return _publish_home(tools_dir, pin=pin, unpacked=prefix)
    finally:
        if build_root.exists():
            shutil.rmtree(build_root, ignore_errors=True)


def fetch_apache(
    spec: ComponentSpec,
    tools_dir: Path,
    *,
    env: dict[str, str] | None = None,
    progress: ProgressFn | None = None,
    quiet: bool = True,
) -> tuple[Path | None, list[Diagnostic]]:
    """
    Ensure ``tools/apache`` home exists.

    Order: bundled cache hit → ``ONEC_APACHE_HOME`` → prebuilt archive URL →
    ASF source build (Unix). Soft failures only.
    """
    del quiet
    report = progress or noop_progress
    diagnostics: list[Diagnostic] = []
    pin = (spec.pin or DEFAULT_PIN).strip() or DEFAULT_PIN
    stable = tools_dir / STABLE_NAME

    if is_bundled_apache_home(stable):
        report(f"→ {spec.id}: cache hit")
        return stable.resolve(), diagnostics

    environ = env if env is not None else os.environ
    if spec.env:
        override = environ.get(spec.env, "").strip()
        if override:
            home = Path(override).expanduser()
            if _looks_like_apache_home(home):
                report(f"→ {spec.id}: env home")
                return home.resolve(), diagnostics

    for url in _archive_urls(spec):
        try:
            installed = _download_and_install(
                url=url, tools_dir=tools_dir, pin=pin, report=report
            )
            if installed is not None:
                report(f"✓ {spec.id}: archive")
                return installed, diagnostics
            diagnostics.append(
                warning(
                    "Архив Apache скачан, но bin/httpd+modules не найдены",
                    code="1CT040",
                    source="toolchain",
                    suggestion=(
                        "Проверьте urls в toolchain/manifest.yaml "
                        "или задайте ONEC_APACHE_HOME / ./scripts/fetch-apache.sh."
                    ),
                )
            )
        except (urllib.error.URLError, OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
            diagnostics.append(
                warning(
                    f"Не удалось скачать Apache: {exc}",
                    code="1CT040",
                    source="toolchain",
                    suggestion="Проверьте сеть или ./scripts/fetch-apache.sh.",
                )
            )

    build_urls = _build_urls(spec)
    if build_urls is not None:
        try:
            installed = _build_from_source(
                urls=build_urls, tools_dir=tools_dir, pin=pin, report=report
            )
            report(f"✓ {spec.id}: built from ASF sources")
            return installed, diagnostics
        except (urllib.error.URLError, OSError, tarfile.TarError) as exc:
            diagnostics.append(
                warning(
                    f"Не удалось собрать Apache из исходников: {exc}",
                    code="1CT041",
                    source="toolchain",
                    suggestion=(
                        "Установите build-essential libpcre2-dev libexpat1-dev "
                        "или выполните ./scripts/fetch-apache.sh "
                        "или задайте ONEC_APACHE_HOME."
                    ),
                )
            )

    diagnostics.append(
        warning(
            "Apache httpd для publish/webinst не найден в cache",
            code="1CT041",
            source="toolchain",
            suggestion=(
                "Выполните 1c-dev tools sync / ./scripts/fetch-apache.sh "
                "или задайте ONEC_APACHE_HOME на prefix с bin/httpd и modules/."
            ),
        )
    )
    return None, diagnostics
