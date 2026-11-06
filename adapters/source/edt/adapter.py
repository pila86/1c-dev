"""EdtSourceAdapter: detect / inspect / read → Metadata IR (ADR-032 / #152)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from adapters.source.edt.detect import EdtDetectResult, detect_edt, validate_edt_source_dir
from adapters.source.edt.inspect import EdtInspectInfo, inspect_edt
from adapters.source.mdclasses import MdReaderError, run_md_reader

Command = Literal["list", "get", "find"]


class EdtSourceError(Exception):
    """EDT layout / detect failure before md-reader."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.suggestion = suggestion


class EdtSourceAdapter:
    """
    Source Adapter для ``source.format: edt`` (волна 2 M7 / #152).

    Read идёт через MDClasses (md-reader) с корня EDT-проекта.
    Write (md-sparrow apply-mutation) — #153 / #154.
    """

    def detect(self, path: Path) -> EdtDetectResult:
        return detect_edt(path)

    def inspect(self, path: Path) -> EdtInspectInfo:
        return inspect_edt(path)

    def validate(self, path: Path) -> EdtDetectResult:
        return validate_edt_source_dir(path)

    def read(
        self,
        command: Command,
        source_dir: Path,
        *args: str,
    ) -> dict[str, Any]:
        """
        Read Metadata IR via md-reader.

        ``source_dir`` — корень EDT-проекта (``.project`` / ``src/…``).
        """
        checked = validate_edt_source_dir(source_dir)
        if not checked.is_edt:
            raise EdtSourceError(
                checked.message or "EDT layout detect failed",
                code=checked.code or "1CS003",
                suggestion=checked.suggestion,
            )
        try:
            return run_md_reader(command, checked.path, *args)
        except MdReaderError:
            raise
