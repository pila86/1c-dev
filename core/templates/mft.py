"""Parse platform template manifests (*.mft) — INI-like UTF-8/BOM (ADR-024 / #91)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_SECTION_RE = re.compile(r"^\[([^\]]+)\]\s*$")
_SOURCE_KIND_BY_SUFFIX = {
    ".cf": "cf",
    ".dt": "dt",
    ".cfu": "cfu",
}


@dataclass(frozen=True)
class MftSection:
    """One [ConfigN] (or similar) section inside an *.mft."""

    name: str
    catalog: str | None = None
    destination: str | None = None
    source: str | None = None
    extra: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MftManifest:
    """Parsed *.mft file (global Vendor/Name/Version + sections)."""

    path: Path
    vendor: str | None = None
    name: str | None = None
    version: str | None = None
    app_version: str | None = None
    globals: dict[str, str] = field(default_factory=dict)
    sections: list[MftSection] = field(default_factory=list)


def source_kind(source: str | None) -> str | None:
    """Map Source filename to cf / dt / cfu (or None)."""
    if not source:
        return None
    suffix = Path(source).suffix.casefold()
    return _SOURCE_KIND_BY_SUFFIX.get(suffix)


def parse_mft_text(text: str, *, path: Path | None = None) -> MftManifest:
    """Parse INI-like mft content into structured manifest."""
    cleaned = text.lstrip("\ufeff")
    globals_: dict[str, str] = {}
    sections: list[MftSection] = []
    current_name: str | None = None
    current_data: dict[str, str] = {}

    def flush() -> None:
        nonlocal current_name, current_data
        if current_name is None:
            return
        known = {
            "catalog": current_data.pop("Catalog", None)
            or current_data.pop("catalog", None),
            "destination": current_data.pop("Destination", None)
            or current_data.pop("destination", None),
            "source": current_data.pop("Source", None)
            or current_data.pop("source", None),
        }
        sections.append(
            MftSection(
                name=current_name,
                catalog=known["catalog"],
                destination=known["destination"],
                source=known["source"],
                extra=dict(current_data),
            )
        )
        current_name = None
        current_data = {}

    for raw_line in cleaned.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        section_match = _SECTION_RE.match(line)
        if section_match:
            flush()
            current_name = section_match.group(1).strip()
            current_data = {}
            continue
        key, sep, value = line.partition("=")
        if sep != "=":
            continue
        key_s = key.strip()
        value_s = value.strip()
        if current_name is None:
            globals_[key_s] = value_s
        else:
            current_data[key_s] = value_s

    flush()

    def g(name: str) -> str | None:
        if name in globals_:
            return globals_[name]
        for k, v in globals_.items():
            if k.casefold() == name.casefold():
                return v
        return None

    return MftManifest(
        path=path or Path("."),
        vendor=g("Vendor"),
        name=g("Name"),
        version=g("Version"),
        app_version=g("AppVersion"),
        globals=dict(globals_),
        sections=sections,
    )


def parse_mft_file(path: Path) -> MftManifest:
    """Read and parse an *.mft file (utf-8-sig, fallback cp1251)."""
    raw = path.read_bytes()
    text: str
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1251")
    return parse_mft_text(text, path=path.resolve())
