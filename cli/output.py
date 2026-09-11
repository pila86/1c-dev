"""Shared CLI output format."""

from __future__ import annotations

from enum import Enum


class OutputFormat(str, Enum):
    text = "text"
    json = "json"
