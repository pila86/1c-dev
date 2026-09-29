"""Validate project manifest against JSON Schema (schema "1" / "2")."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from core.diagnostics import Diagnostic, error
from core.project.constants import HOME_MANIFEST_REL, LEGACY_MANIFEST_NAME, MANIFEST_NAME
from core.project.detect import detect_manifest
from core.project.load import load_manifest
from core.project.paths import (
    is_home_manifest,
    project_home,
    runtimes_summary,
    scope_root_from_manifest,
)
from core.project.result import ProjectResult

_SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "schemas"
_SCHEMA_V1_PATH = _SCHEMAS_DIR / "1c.project.schema.json"
_SCHEMA_V2_PATH = _SCHEMAS_DIR / "1c.project.schema.v2.json"
_SUPPORTED_SCHEMAS = frozenset({"1", "2"})


@lru_cache(maxsize=2)
def _validator(version: str) -> Draft202012Validator:
    path = _SCHEMA_V1_PATH if version == "1" else _SCHEMA_V2_PATH
    with path.open(encoding="utf-8") as fh:
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


def _invariant_error(message: str) -> Diagnostic:
    return error(
        f"Манифест не соответствует schema: {message}",
        code="1CP003",
        file=MANIFEST_NAME,
    )


def _validate_v2_invariants(data: dict[str, Any]) -> list[Diagnostic]:
    """Семантические инварианты ADR-023/025/026 поверх JSON Schema v2."""
    diags: list[Diagnostic] = []

    configurations = data.get("configurations")
    runtimes = data.get("runtimes")
    if not isinstance(configurations, list) or not isinstance(runtimes, list):
        return diags

    config_ids: list[str] = []
    default_configs = 0
    for idx, conf in enumerate(configurations):
        if not isinstance(conf, dict):
            continue
        conf_id = conf.get("id")
        if isinstance(conf_id, str) and conf_id:
            if conf_id in config_ids:
                diags.append(
                    _invariant_error(
                        f"configurations[{idx}].id: дублируется id {conf_id!r}"
                    )
                )
            else:
                config_ids.append(conf_id)
        if conf.get("default") is True:
            default_configs += 1

    if default_configs > 1:
        diags.append(
            _invariant_error(
                "configurations: не более одной configuration с default: true"
            )
        )

    config_id_set = set(config_ids)
    runtime_ids: list[str] = []
    default_runtimes = 0
    covered_configs: set[str] = set()

    for idx, rt in enumerate(runtimes):
        if not isinstance(rt, dict):
            continue
        rt_id = rt.get("id")
        if isinstance(rt_id, str) and rt_id:
            if rt_id in runtime_ids:
                diags.append(
                    _invariant_error(f"runtimes[{idx}].id: дублируется id {rt_id!r}")
                )
            else:
                runtime_ids.append(rt_id)

        conf_ref = rt.get("configuration")
        if isinstance(conf_ref, str) and conf_ref:
            if conf_ref not in config_id_set:
                diags.append(
                    _invariant_error(
                        f"runtimes[{idx}].configuration: "
                        f"нет configuration с id {conf_ref!r}"
                    )
                )
            else:
                covered_configs.add(conf_ref)

        if rt.get("default") is True:
            default_runtimes += 1

    for conf_id in config_ids:
        if conf_id not in covered_configs:
            diags.append(
                _invariant_error(
                    f"configurations: у {conf_id!r} нет ни одного runtime "
                    f"(нужен ≥1 элемент в runtimes[] с configuration: {conf_id!r})"
                )
            )

    # Empty scope (оба массива пусты) — OK до configuration.add (#100).
    # «Ровно один default» — только когда runtimes непуст.
    if runtimes and default_runtimes != 1:
        diags.append(
            _invariant_error(
                "runtimes: ровно один элемент с default: true "
                f"(сейчас {default_runtimes})"
            )
        )

    publish = data.get("publish")
    if not isinstance(publish, dict):
        return diags

    profiles = publish.get("profiles")
    profile_ids: set[str] = set()
    if isinstance(profiles, dict):
        profile_ids = {str(k) for k in profiles}
        runtime_id_set = set(runtime_ids)
        for profile_id, profile in profiles.items():
            if not isinstance(profile, dict):
                continue
            rt_ref = profile.get("runtime")
            if isinstance(rt_ref, str) and rt_ref and rt_ref not in runtime_id_set:
                diags.append(
                    _invariant_error(
                        f"publish.profiles.{profile_id}.runtime: "
                        f"нет runtime с id {rt_ref!r}"
                    )
                )

    default_profile = publish.get("default")
    if isinstance(default_profile, str) and default_profile:
        if default_profile not in profile_ids:
            diags.append(
                _invariant_error(
                    f"publish.default: нет профиля с id {default_profile!r}"
                )
            )

    return diags


def validate_manifest(data: dict[str, Any]) -> list[Diagnostic]:
    """Провалидировать уже загруженный dict по JSON Schema (+ инварианты v2)."""
    version = data.get("schema")
    if version not in _SUPPORTED_SCHEMAS:
        shown = version if isinstance(version, str) else type(version).__name__
        return [
            error(
                f"Манифест не соответствует schema: "
                f"неподдерживаемая версия schema {shown!r} "
                f"(ожидается \"1\" или \"2\")",
                code="1CP003",
                file=MANIFEST_NAME,
            )
        ]

    validator = _validator(version)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    diags = [_schema_diagnostics(err) for err in errors]
    if diags:
        return diags

    if version == "2":
        diags.extend(_validate_v2_invariants(data))
    return diags


def validate_project(start: Path | None = None) -> ProjectResult:
    """Detect + load + schema-validate манифест относительно start/CWD."""
    path = detect_manifest(start)
    if path is None:
        return ProjectResult(
            status="error",
            diagnostics=[
                error(
                    f"Манифест проекта не найден "
                    f"({HOME_MANIFEST_REL} или {LEGACY_MANIFEST_NAME})",
                    code="1CP001",
                    file=HOME_MANIFEST_REL,
                )
            ],
        )

    root = scope_root_from_manifest(path)
    home = project_home(root) if is_home_manifest(path) else None

    data, load_diags = load_manifest(path)
    if data is None:
        return ProjectResult(
            status="error",
            path=path,
            root=root,
            home=home,
            diagnostics=load_diags,
        )

    schema_diags = validate_manifest(data)
    runtimes = runtimes_summary(data)
    if schema_diags:
        return ProjectResult(
            status="error",
            path=path,
            root=root,
            home=home,
            manifest=data,
            runtimes=runtimes,
            diagnostics=schema_diags,
        )

    return ProjectResult(
        status="ok",
        path=path,
        root=root,
        home=home,
        manifest=data,
        runtimes=runtimes,
    )
