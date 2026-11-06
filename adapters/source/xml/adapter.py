"""XmlSourceAdapter: detect / inspect / read → Metadata IR (PRD §50 / #158)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from adapters.source.capabilities import SourceFormat, capabilities_payload
from adapters.source.mdclasses import MdReaderError, run_md_reader
from adapters.source.xml.detect import XmlDetectResult, detect_xml, validate_xml_source_dir
from adapters.source.xml.inspect import XmlInspectInfo, inspect_xml

Command = Literal["list", "get", "find"]


class XmlSourceError(Exception):
    """XML layout / detect failure before md-reader."""

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


class XmlSourceAdapter:
    """
    Source Adapter для ``source.format: xml`` (contract #158 / PRD §50).

    Read идёт через MDClasses (md-reader). Write — xml-gen через ``metadata.*``.
    """

    format: SourceFormat = "xml"

    def capabilities(self) -> dict[str, Any]:
        return capabilities_payload(self.format)

    def detect(self, path: Path) -> XmlDetectResult:
        return detect_xml(path)

    def inspect(self, path: Path) -> XmlInspectInfo:
        return inspect_xml(path)

    def validate(self, path: Path) -> XmlDetectResult:
        return validate_xml_source_dir(path)

    def read(
        self,
        command: Command,
        source_dir: Path,
        *args: str,
    ) -> dict[str, Any]:
        """
        Read Metadata IR via md-reader.

        ``source_dir`` — каталог Designer XML с ``Configuration.xml``.
        """
        checked = validate_xml_source_dir(source_dir)
        if not checked.is_xml:
            raise XmlSourceError(
                checked.message or "XML layout detect failed",
                code=checked.code or "1CS012",
                suggestion=checked.suggestion,
            )
        try:
            return run_md_reader(command, checked.path, *args)
        except MdReaderError:
            raise
