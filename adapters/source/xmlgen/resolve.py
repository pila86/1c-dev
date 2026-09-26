"""Resolve xml-gen jar and Java runtime (ADR-007)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from adapters.source.xmlgen.constants import MIN_JAVA_MAJOR, XMLGEN_COMMIT, XMLGEN_JAR_ENV
from core.toolchain.cache import tools_cache_dir as _tools_cache_dir

_JAVA_VERSION_RE = re.compile(r'version\s+"?(?P<ver>\d+)(?:\.(?P<minor>\d+))?')


@dataclass(frozen=True)
class ToolResolve:
    """Resolved external binary or jar."""

    found: bool
    path: Path | None = None
    version: str | None = None


def tools_cache_dir() -> Path:
    """OS-specific cache directory for toolchain jars."""
    return _tools_cache_dir()


def default_jar_path() -> Path:
    """Stable symlink/copy name in cache."""
    return tools_cache_dir() / "xml-gen.jar"


def pinned_jar_path() -> Path:
    """Versioned jar name for pinned commit."""
    short = XMLGEN_COMMIT[:12]
    return tools_cache_dir() / f"xml-gen-{short}.jar"


def fetch_script_suggestion() -> str:
    """OS-specific hint to bootstrap xml-gen."""
    if sys.platform == "win32":
        return "1c-dev doctor --fix  # или: 1c-dev tools sync / pwsh scripts/fetch-xml-gen.ps1"
    return "1c-dev doctor --fix  # или: 1c-dev tools sync / ./scripts/fetch-xml-gen.sh"


def resolve_jar(*, env: dict[str, str] | None = None) -> ToolResolve:
    """Find xml-gen jar: ONEC_XMLGEN_JAR, then cache xml-gen.jar."""
    environ = env if env is not None else os.environ
    override = environ.get(XMLGEN_JAR_ENV, "").strip()
    if override:
        path = Path(override).expanduser()
        if path.is_file():
            return ToolResolve(found=True, path=path.resolve())
        return ToolResolve(found=False, path=path)
    cached = default_jar_path()
    if cached.is_file():
        return ToolResolve(found=True, path=cached.resolve())
    pinned = pinned_jar_path()
    if pinned.is_file():
        return ToolResolve(found=True, path=pinned.resolve())
    return ToolResolve(found=False, path=cached)


def _java_candidates(*, env: dict[str, str] | None = None) -> list[Path]:
    environ = env if env is not None else os.environ
    candidates: list[Path] = []
    java_home = environ.get("JAVA_HOME", "").strip()
    if java_home:
        home = Path(java_home)
        if sys.platform == "win32":
            candidates.append(home / "bin" / "java.exe")
        else:
            candidates.append(home / "bin" / "java")
    which = shutil.which("java", path=environ.get("PATH"))
    if which:
        candidates.append(Path(which))
    # When PATH still points at an older JDK, probe common Linux install roots.
    if sys.platform != "win32":
        jvm_root = Path("/usr/lib/jvm")
        if jvm_root.is_dir():
            for pattern in ("java-21*", "java-1.21*", "temurin-21*", "zulu-21*"):
                for home in sorted(jvm_root.glob(pattern), reverse=True):
                    candidates.append(home / "bin" / "java")
    # Deduplicate while preserving order
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def _parse_java_major(output: str) -> tuple[int | None, str | None]:
    # java -version prints to stderr
    for line in output.splitlines():
        m = _JAVA_VERSION_RE.search(line)
        if not m:
            continue
        major = int(m.group("ver"))
        # Legacy: 1.8.0_xxx → major 8
        if major == 1 and m.group("minor"):
            major = int(m.group("minor"))
        return major, line.strip()
    return None, None


def resolve_java(
    *,
    env: dict[str, str] | None = None,
    min_major: int | None = None,
) -> ToolResolve:
    """Find Java >= min_major (default: xml-gen MIN_JAVA_MAJOR)."""
    required = MIN_JAVA_MAJOR if min_major is None else min_major
    for candidate in _java_candidates(env=env):
        if not candidate.is_file() and shutil.which(str(candidate)) is None:
            # Path from JAVA_HOME may not exist
            if not candidate.exists():
                continue
        try:
            proc = subprocess.run(
                [str(candidate), "-version"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            continue
        text = (proc.stderr or "") + (proc.stdout or "")
        major, line = _parse_java_major(text)
        if major is None:
            continue
        if major < required:
            continue
        return ToolResolve(found=True, path=candidate.resolve(), version=str(major))
    return ToolResolve(found=False)
