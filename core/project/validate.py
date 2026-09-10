"""Validate project manifest against JSON Schema."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from core.diagnostics import Diagnostic, error
from core.project.constants import MANIFEST_NAME
from core.project.detect import detect_manifest
from core.project.load import load_manifest
from core.project.result import ProjectResult

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "schemas" / "1c.project.schema.json"
)


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    with _SCHEMA_PATH.open(encoding="utf-8") as fh:
        schema = json.load(fh)
    return Draft202012Validator(schema)


def _schema_diagnostics(exc: ValidationError) -> Diagnostic:
    path = ".".join(str(p) for p in exc.absolute_path)
    detail = f"{path}: {exc.message}" if path else exc.message
    return error(
        f"Манифест не соответствует schema: {detail}",
        code="1CP003",
        file=MANIFEST_NAME,
    )


def validate_manifest(data: dict[str, Any]) -> list[Diagnostic]:
    """Провалидировать уже загруженный dict по JSON Schema."""
    validator = _validator()
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    return [_schema_diagnostics(err) for err in errors]


def validate_project(start: Path | None = None) -> ProjectResult:
    """Detect + load + schema-validate манифест относительно start/CWD."""
    path = detect_manifest(start)
    if path is None:
        return ProjectResult(
            status="error",
            diagnostics=[
                error(
                    f"Файл {MANIFEST_NAME} не найден",
                    code="1CP001",
                    file=MANIFEST_NAME,
                )
            ],
        )

    data, load_diags = load_manifest(path)
    if data is None:
        return ProjectResult(
            status="error",
            path=path,
            root=path.parent,
            diagnostics=load_diags,
        )

    schema_diags = validate_manifest(data)
    if schema_diags:
        return ProjectResult(
            status="error",
            path=path,
            root=path.parent,
            manifest=data,
            diagnostics=schema_diags,
        )

    return ProjectResult(
        status="ok",
        path=path,
        root=path.parent,
        manifest=data,
    )
