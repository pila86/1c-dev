"""Shared helpers for toolchain fetchers."""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path


def pin_artifact_name(artifact: str, pin: str) -> str:
    """Build pinned filename: xml-gen.jar + pin → xml-gen-{pin}.jar."""
    if artifact.endswith(".jar"):
        stem = artifact[: -len(".jar")]
        return f"{stem}-{pin}.jar"
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
    """Return argv for Gradle wrapper in project_dir, if present."""
    if sys.platform == "win32":
        bat = project_dir / "gradlew.bat"
        if bat.is_file():
            return [str(bat)]
    else:
        script = project_dir / "gradlew"
        if script.is_file():
            return [str(script)]
    return None


def find_gradle() -> str | None:
    """Locate system gradle / gradle.bat on PATH."""
    names = ("gradle.bat", "gradle") if sys.platform == "win32" else ("gradle",)
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def find_git() -> str | None:
    return shutil.which("git.exe" if sys.platform == "win32" else "git")
