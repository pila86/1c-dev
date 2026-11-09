"""XML (Designer) Source Adapter constants (PRD §50 / #158)."""

from __future__ import annotations

from adapters.source.edt.constants import SOURCE_FORMAT_EDT, SOURCE_FORMAT_XML

CONFIGURATION_XML_NAME = "Configuration.xml"

# Layout diagnostics (project/source; exit PROJECT_ERROR).
CODE_LAYOUT_NOT_XML = "1CS012"
CODE_PATH_NOT_XML_ROOT = "1CS013"

__all__ = [
    "CODE_LAYOUT_NOT_XML",
    "CODE_PATH_NOT_XML_ROOT",
    "CONFIGURATION_XML_NAME",
    "SOURCE_FORMAT_EDT",
    "SOURCE_FORMAT_XML",
]
