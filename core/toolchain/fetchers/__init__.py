"""Shared helpers for toolchain fetchers."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def run_cmd(
    argv: list[str],
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    quiet: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a command; in quiet mode capture output, otherwise stream to the terminal."""
    if quiet:
        return subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    return subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        text=True,
        check=False,
    )


def pin_artifact_name(artifact: str, pin: str) -> str:
    """Build pinned filename: xml-gen.jar + pin → xml-gen-{pin}.jar (same for .cfe)."""
    for suffix in (".jar", ".cfe"):
        if artifact.endswith(suffix):
            stem = artifact[: -len(suffix)]
            return f"{stem}-{pin}{suffix}"
    return f"{artifact}-{pin}"


def install_jar_pair(*, built: Path, tools_dir: Path, artifact: str, pin: str) -> Path:
    """Copy jar to pinned + stable names under tools_dir; return stable path."""
    tools_dir.mkdir(parents=True, exist_ok=True)
    pinned = tools_dir / pin_artifact_name(artifact, pin)
    stable = tools_dir / artifact
    shutil.copy2(built, pinned)
    shutil.copy2(pinned, stable)
    return stable.resolve()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def gradlew_cmd(project_dir: Path) -> list[str] | None:
    """Return argv for Gradle wrapper in project_dir, if present.

    On Unix invoke via ``sh`` so a missing execute bit (wheel unpack / checkout)
    does not break ``tools sync``.
    """
    if sys.platform == "win32":
        bat = project_dir / "gradlew.bat"
        if bat.is_file():
            return [str(bat)]
    else:
        script = project_dir / "gradlew"
        if script.is_file():
            return ["sh", str(script)]
    return None


def _dir_is_writable(path: Path) -> bool:
    """True if we can create a file under ``path`` (Gradle needs .gradle/build)."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".1c-dev-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


@contextmanager
def writable_gradle_project(src: Path) -> Iterator[Path]:
    """Yield a Gradle project dir that is writable by the current user.

    Wheel/site-packages layouts ship ``tools/md-reader`` read-only for non-root
    (e.g. OpenHands uid 10001). Copy to a temp tree when needed so ``gradlew``
    can create ``.gradle/`` and ``build/``.
    """
    if _dir_is_writable(src):
        yield src
        return
    tmp = Path(tempfile.mkdtemp(prefix="1c-dev-gradle-"))
    try:
        dest = tmp / src.name
        shutil.copytree(
            src,
            dest,
            ignore=shutil.ignore_patterns(".gradle", "build", "bin", ".1c-dev-write-probe"),
        )
        yield dest
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def find_git() -> str | None:
    return shutil.which("git.exe" if sys.platform == "win32" else "git")