"""Run xml-gen meta remove (ADR-011 / #29)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from adapters.source.xmlgen.compile import XmlGenError
from adapters.source.xmlgen.resolve import ToolResolve, resolve_jar, resolve_java

_NOT_FOUND_RE = re.compile(r"not found", re.IGNORECASE)


def remove_metadata(
    source_dir: Path,
    qualified_name: str,
    *,
    jar: ToolResolve | None = None,
    java: ToolResolve | None = None,
) -> list[str]:
    """
    Invoke ``xml-gen meta remove <configDir> <Type.Name> --force``.

    Always passes ``--force`` so inbound Ref checks do not block delete
    (ADR-011: no cascade; dangling Refs allowed until graph / M5).

    Returns relative paths (posix) of files removed under ``source_dir``.
    """
    jar_r = jar if jar is not None else resolve_jar()
    java_r = java if java is not None else resolve_java()
    if not java_r.found or java_r.path is None:
        raise XmlGenError(
            f"Java {17}+ не найдена (нужна для xml-gen)",
            code="1CM006",
        )
    if not jar_r.found or jar_r.path is None:
        raise XmlGenError(
            "xml-gen jar не найден",
            code="1CM006",
        )

    source_dir = source_dir.resolve()
    before = _snapshot(source_dir)

    cmd = [
        str(java_r.path),
        "-jar",
        str(jar_r.path),
        "meta",
        "remove",
        str(source_dir),
        qualified_name,
        "--force",
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        if _NOT_FOUND_RE.search(detail):
            raise XmlGenError(
                detail[:500] if detail else f"Объект не найден: {qualified_name}",
                code="1CM008",
            )
        msg = "xml-gen meta remove завершился с ошибкой"
        if detail:
            msg = f"{msg}: {detail[:500]}"
        raise XmlGenError(msg, code="1CM007")

    after = _snapshot(source_dir)
    return sorted(before - after)


def _snapshot(root: Path) -> set[str]:
    if not root.is_dir():
        return set()
    out: set[str] = set()
    for path in root.rglob("*"):
        if path.is_file():
            out.add(path.relative_to(root).as_posix())
    return out
