"""Platform configuration templates (tmplts / *.mft) — ADR-024 / #91."""

from __future__ import annotations

from core.templates.api import (
    CODE_NOT_FOUND,
    CODE_ROOTS_EMPTY,
    TemplateInfo,
    TemplatesGetResult,
    TemplatesListResult,
    TemplatesRootsResult,
    collect_templates,
    make_template_id,
    templates_get,
    templates_list,
    templates_roots,
)
from core.templates.mft import MftManifest, MftSection, parse_mft_file, parse_mft_text

__all__ = [
    "CODE_NOT_FOUND",
    "CODE_ROOTS_EMPTY",
    "MftManifest",
    "MftSection",
    "TemplateInfo",
    "TemplatesGetResult",
    "TemplatesListResult",
    "TemplatesRootsResult",
    "collect_templates",
    "make_template_id",
    "parse_mft_file",
    "parse_mft_text",
    "templates_get",
    "templates_list",
    "templates_roots",
]
