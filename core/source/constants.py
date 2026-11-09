"""Constants for source.convert (ADR-032 / #156)."""

from __future__ import annotations

from adapters.edtcli.constants import CODE_CONVERT_DIRTY
from adapters.source.edt.constants import SOURCE_FORMAT_EDT, SOURCE_FORMAT_XML
from core.import_cf.constants import CODE_PROJECT

CODE_PROJECT_MISSING = CODE_PROJECT

# Names kept when source.path is the project root (same idea as project.clean).
ROOT_PRESERVE_NAMES = frozenset(
    {
        ".1c-dev",
        ".git",
        ".gitignore",
        ".gitattributes",
        ".cursor",
        ".vscode",
        ".idea",
        "AGENTS.md",
        "README.md",
        "LICENSE",
        "LICENSE.md",
    }
)

CONVERT_TARGETS = frozenset({SOURCE_FORMAT_EDT, SOURCE_FORMAT_XML})

__all__ = [
    "CODE_CONVERT_DIRTY",
    "CODE_PROJECT_MISSING",
    "CONVERT_TARGETS",
    "ROOT_PRESERVE_NAMES",
    "SOURCE_FORMAT_EDT",
    "SOURCE_FORMAT_XML",
]
