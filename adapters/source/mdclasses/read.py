"""Invoke md-reader jar (MDClasses → IR JSON, ADR-012)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Literal

from adapters.source.mdclasses.resolve import (
    ToolResolve,
    fetch_script_suggestion,
    resolve_jar,
    resolve_java,
)

Command = Literal["list", "get", "find"]


class MdReaderError(Exception):
    """md-reader subprocess or environment failure."""

    def __init__(self, message: str, *, code: str = "1CM007") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def run_md_reader(
    command: Command,
    source_dir: Path,
    *args: str,
    jar: ToolResolve | None = None,
    java: ToolResolve | None = None,
) -> dict[str, Any]:
    """
    Run `java -jar md-reader.jar <command> <sourceDir> [args...]`.

    Returns parsed JSON envelope: {status, objects?} | {status, object?} | {status, code, message}.
    """
    jar_r = jar if jar is not None else resolve_jar()
    java_r = java if java is not None else resolve_java()
    if not java_r.found or java_r.path is None:
        raise MdReaderError(
            f"Java {21}+ не найдена (нужна для md-reader / MDClasses)",
            code="1CM006",
        )
    if not jar_r.found or jar_r.path is None:
        raise MdReaderError(
            f"md-reader jar не найден (соберите: {fetch_script_suggestion()})",
            code="1CM006",
        )

    source_dir = source_dir.resolve()
    cmd = [
        str(java_r.path),
        "-jar",
        str(jar_r.path),
        command,
        str(source_dir),
        *args,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise MdReaderError(f"Не удалось запустить md-reader: {exc}", code="1CM007") from exc

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if not stdout:
        detail = stderr or f"exit {proc.returncode}"
        raise MdReaderError(f"md-reader не вернул JSON: {detail[:500]}", code="1CM007")

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise MdReaderError(
            f"md-reader вернул невалидный JSON: {stdout[:200]}",
            code="1CM007",
        ) from exc

    if not isinstance(payload, dict):
        raise MdReaderError("md-reader: ожидается JSON-объект", code="1CM007")

    if payload.get("status") == "error":
        code = str(payload.get("code") or "1CM007")
        message = str(payload.get("message") or "md-reader error")
        raise MdReaderError(message, code=code)

    if proc.returncode != 0 and payload.get("status") != "ok":
        detail = stderr or stdout[:300]
        raise MdReaderError(f"md-reader завершился с ошибкой: {detail}", code="1CM007")

    return payload
