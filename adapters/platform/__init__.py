"""Platform installation and tool discovery."""

from __future__ import annotations

from .discovery import (
    DiscoveryResult,
    PlatformInfo,
    ToolInfo,
    discover_environment,
    version_from_path,
)
from .templates import (
    TemplateRootsResult,
    default_tmplts_roots,
    discover_template_roots,
    onecestart_cfg_candidates,
    parse_configuration_templates_locations,
)

__all__ = [
    "DiscoveryResult",
    "PlatformInfo",
    "TemplateRootsResult",
    "ToolInfo",
    "default_tmplts_roots",
    "discover_environment",
    "discover_template_roots",
    "onecestart_cfg_candidates",
    "parse_configuration_templates_locations",
    "version_from_path",
]
