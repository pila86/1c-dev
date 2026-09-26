"""Invoke docs-facade jar (bsl-context → docs index, ADR-017)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Literal

from adapters.docs.resolve import (
    ToolResolve,
    fetch_script_suggestion,
    resolve_jar,
    resolve_java,
)

Command = Literal["ensure", "search", "get"]


class DocsFacadeError(Exception):
    """docs-facade subprocess or environment failure."""

    def __init__(self, message: str, *, code: str = "1CX005") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def run_docs_facade(
    command: Command,
    *extra_args: str,
    jar: ToolResolve | None = None,
    java: ToolResolve | None = None,
) -> dict[str, Any]:
    """
    Run `java -jar docs-facade.jar <command> [args...]`.

    Returns parsed JSON envelope.
    """
    jar_r = jar if jar is not None else resolve_jar()
    java_r = java if java is not None else resolve_java()
    if not java_r.found or java_r.path is None:
        raise DocsFacadeError(
            "Java 21+ не найдена (нужна для docs-facade / bsl-context)",
            code="1CX001",
        )
    if not jar_r.found or jar_r.path is None:
        raise DocsFacadeError(
            f"docs-facade jar не найден (соберите: {fetch_script_suggestion()})",
            code="1CX001",
        )

    cmd = [
        str(java_r.path),
        "-jar",
        str(jar_r.path),
        command,
        *extra_args,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise DocsFacadeError(
            f"Не удалось запустить docs-facade: {exc}",
            code="1CX005",
        ) from exc

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if not stdout:
        detail = stderr or f"exit {proc.returncode}"
        raise DocsFacadeError(
            f"docs-facade не вернул JSON: {detail[:500]}",
            code="1CX005",
        )

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise DocsFacadeError(
            f"docs-facade вернул невалидный JSON: {stdout[:200]}",
            code="1CX005",
        ) from exc

    if not isinstance(payload, dict):
        raise DocsFacadeError("docs-facade: ожидается JSON-объект", code="1CX005")

    if payload.get("status") == "error":
        code = str(payload.get("code") or "1CX005")
        message = str(payload.get("message") or "docs-facade error")
        raise DocsFacadeError(message, code=code)

    if proc.returncode != 0 and payload.get("status") != "ok":
        detail = stderr or stdout[:300]
        raise DocsFacadeError(
            f"docs-facade завершился с ошибкой: {detail}",
            code="1CX005",
        )

    return payload


def ensure_index(
    *,
    index_dir: Path,
    platform_version: str,
    hbk: Path,
    force: bool = False,
    jar: ToolResolve | None = None,
    java: ToolResolve | None = None,
) -> dict[str, Any]:
    """Build or validate the docs index for a platform version."""
    args = [
        "--index-dir",
        str(index_dir),
        "--platform-version",
        platform_version,
        "--hbk",
        str(hbk),
    ]
    if force:
        args.append("--force")
    return run_docs_facade("ensure", *args, jar=jar, java=java)


def search_index(
    *,
    index_dir: Path,
    query: str,
    limit: int = 20,
    jar: ToolResolve | None = None,
    java: ToolResolve | None = None,
) -> dict[str, Any]:
    """Search the docs index."""
    return run_docs_facade(
        "search",
        "--index-dir",
        str(index_dir),
        "--query",
        query,
        "--limit",
        str(limit),
        jar=jar,
        java=java,
    )


def get_index_entry(
    *,
    index_dir: Path,
    name: str,
    jar: ToolResolve | None = None,
    java: ToolResolve | None = None,
) -> dict[str, Any]:
    """Get a single docs entry by name / Owner.Member."""
    return run_docs_facade(
        "get",
        "--index-dir",
        str(index_dir),
        "--name",
        name,
        jar=jar,
        java=java,
    )
