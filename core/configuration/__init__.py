"""Configuration lifecycle API (ADR-027 / #100)."""

from __future__ import annotations

from core.configuration.add import add_configuration
from core.configuration.get import get_configuration
from core.configuration.list import ConfigurationListResult, list_configurations
from core.configuration.remove import remove_configuration
from core.configuration.set_default import set_default_configuration

__all__ = [
    "ConfigurationListResult",
    "add_configuration",
    "get_configuration",
    "list_configurations",
    "remove_configuration",
    "set_default_configuration",
]
