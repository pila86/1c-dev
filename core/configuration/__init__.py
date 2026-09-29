"""Configuration lifecycle API (ADR-027 / ADR-028 / #100)."""

from __future__ import annotations

from core.configuration.add import CODE_CONF_EXISTS, add_configuration
from core.configuration.get import get_configuration
from core.configuration.list import ConfigurationListResult, list_configurations
from core.configuration.register import register_configuration_entry, write_manifest_yaml
from core.configuration.remove import remove_configuration
from core.configuration.set_default import set_default_configuration

__all__ = [
    "CODE_CONF_EXISTS",
    "ConfigurationListResult",
    "add_configuration",
    "get_configuration",
    "list_configurations",
    "register_configuration_entry",
    "remove_configuration",
    "set_default_configuration",
    "write_manifest_yaml",
]
