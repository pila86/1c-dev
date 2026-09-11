"""Load and parse 1c.project.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from core.diagnostics import Diagnostic, error
from core.project.constants import MANIFEST_NAME


def load_manifest(path: Path) -> tuple[dict[str, Any] | None, list[Diagnostic]]:
    """Прочитать YAML-манифест.

    Returns:
        (data, diagnostics). data is None on parse/type errors.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [
            error(
                f"Не удалось прочитать манифест: {exc}",
                code="1CP002",
                file=MANIFEST_NAME,
            )
        ]

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return None, [
            error(
                f"Ошибка разбора YAML: {exc}",
                code="1CP002",
                file=MANIFEST_NAME,
            )
        ]

    if data is None:
        return None, [
            error(
                "Манифест пуст",
                code="1CP002",
                file=MANIFEST_NAME,
            )
        ]

    if not isinstance(data, dict):
        return None, [
            error(
                "Корень манифеста должен быть объектом (mapping)",
                code="1CP002",
                file=MANIFEST_NAME,
            )
        ]

    return data, []
