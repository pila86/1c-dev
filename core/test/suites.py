"""Resolve configurations[].tests suites and extension names (ADR-029)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from adapters.test_yaxunit import RUNNER_EXTENSION_NAME, prepare_filter_extensions
from adapters.test_yaxunit.config import YaxunitConfigError
from core.diagnostics import Diagnostic, error
from core.project.resolve import ResolvedTarget
from core.test.constants import (
    CODE_FILTER,
    CODE_NO_SUITES,
    CODE_RUNNER_UNSUPPORTED,
    CODE_SUITE_UNKNOWN,
    RUNNER_VANESSA,
    RUNNER_YAXUNIT,
    SUPPORTED_RUNNERS,
)


@dataclass(frozen=True)
class ExtensionRef:
    """Test-extension referenced by a suite (manifest id → platform name)."""

    id: str
    name: str
    purpose: str | None
    source_rel: str | None
    source_format: str | None


@dataclass(frozen=True)
class SuiteRef:
    """One ``configurations[].tests[]`` entry with resolved extensions."""

    id: str
    runner: str
    extensions: tuple[ExtensionRef, ...]


def _extension_index(configuration: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = configuration.get("extensions")
    if not isinstance(raw, list):
        return {}
    index: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        ext_id = item.get("id")
        if isinstance(ext_id, str) and ext_id:
            index[ext_id] = item
    return index


def _extension_ref(ext_id: str, raw: dict[str, Any]) -> ExtensionRef:
    name = raw.get("name")
    purpose = raw.get("purpose")
    source = raw.get("source")
    source_rel: str | None = None
    source_format: str | None = None
    if isinstance(source, dict):
        path = source.get("path")
        if isinstance(path, str) and path:
            source_rel = path
        fmt = source.get("format")
        if fmt is not None:
            source_format = str(fmt)
    return ExtensionRef(
        id=ext_id,
        name=name if isinstance(name, str) and name else ext_id,
        purpose=purpose if isinstance(purpose, str) else None,
        source_rel=source_rel,
        source_format=source_format,
    )


def parse_suites(configuration: dict[str, Any]) -> tuple[list[SuiteRef] | None, list[Diagnostic]]:
    """
    Parse ``configurations[].tests`` into suite refs.

    Missing / empty ``tests`` → PROJECT-level diagnostics (caller maps exit).
    """
    tests = configuration.get("tests")
    if tests is None:
        return None, [
            error(
                "В configuration нет секции tests[]",
                code=CODE_NO_SUITES,
                source="test",
                suggestion="Добавьте configurations[].tests (suite: id, runner, extensions)",
            )
        ]
    if not isinstance(tests, list) or not tests:
        return None, [
            error(
                "configurations[].tests пуст — нет suite для Test API",
                code=CODE_NO_SUITES,
                source="test",
                suggestion="Добавьте хотя бы один suite с runner: yaxunit",
            )
        ]

    ext_index = _extension_index(configuration)
    suites: list[SuiteRef] = []
    for item in tests:
        if not isinstance(item, dict):
            continue
        suite_id = item.get("id")
        runner = item.get("runner")
        ext_refs = item.get("extensions")
        if not isinstance(suite_id, str) or not suite_id:
            continue
        if not isinstance(runner, str) or not runner:
            continue
        if not isinstance(ext_refs, list) or not ext_refs:
            continue
        resolved: list[ExtensionRef] = []
        for ref in ext_refs:
            if not isinstance(ref, str) or not ref:
                continue
            raw = ext_index.get(ref)
            if raw is None:
                return None, [
                    error(
                        f"suite {suite_id!r}: нет extension id={ref!r}",
                        code=CODE_FILTER,
                        source="test",
                    )
                ]
            resolved.append(_extension_ref(ref, raw))
        if not resolved:
            continue
        suites.append(
            SuiteRef(id=suite_id, runner=runner.strip().lower(), extensions=tuple(resolved))
        )

    if not suites:
        return None, [
            error(
                "Не удалось разобрать configurations[].tests",
                code=CODE_NO_SUITES,
                source="test",
            )
        ]
    return suites, []


def select_suites(
    suites: list[SuiteRef],
    *,
    suite_id: str | None,
) -> tuple[list[SuiteRef] | None, list[Diagnostic]]:
    """Select one suite by id or all suites (ADR-029 multi-suite default)."""
    if suite_id is None:
        return list(suites), []
    for suite in suites:
        if suite.id == suite_id:
            return [suite], []
    known = ", ".join(s.id for s in suites) or "—"
    return None, [
        error(
            f"Неизвестный suite id={suite_id!r}",
            code=CODE_SUITE_UNKNOWN,
            source="test",
            suggestion=f"Доступные suite id: {known}",
        )
    ]


def require_supported_runners(suites: list[SuiteRef]) -> list[Diagnostic]:
    """Reject vanessa / unknown runners for run / runOne (v1 = yaxunit only)."""
    diags: list[Diagnostic] = []
    for suite in suites:
        if suite.runner in SUPPORTED_RUNNERS:
            continue
        if suite.runner == RUNNER_VANESSA:
            message = (
                f"suite {suite.id!r}: adapter для runner {RUNNER_VANESSA!r} "
                f"не реализован (follow-up #128)"
            )
            suggestion = (
                f"Укажите runner: {RUNNER_YAXUNIT} или --suite с yaxunit; "
                f"adapters/test_vanessa — #128"
            )
        else:
            message = (
                f"suite {suite.id!r}: runner {suite.runner!r} не поддерживается "
                f"(доступен {RUNNER_YAXUNIT})"
            )
            suggestion = f"Укажите runner: {RUNNER_YAXUNIT} или --suite с yaxunit"
        diags.append(
            error(
                message,
                code=CODE_RUNNER_UNSUPPORTED,
                source="test",
                suggestion=suggestion,
            )
        )
    return diags


def filter_extension_names(suites: list[SuiteRef]) -> tuple[list[str] | None, list[Diagnostic]]:
    """
    ``filter.extensions = ∪ suite.extensions[].name`` without YAXUNIT (ADR-029 §6).
    """
    names: list[str] = []
    for suite in suites:
        for ext in suite.extensions:
            names.append(ext.name)
    try:
        return prepare_filter_extensions(
            names,
            runner_names=(RUNNER_EXTENSION_NAME,),
        ), []
    except YaxunitConfigError as exc:
        return None, [
            error(exc.message, code=CODE_FILTER, source="test")
        ]


def suites_payload(suites: list[SuiteRef]) -> list[dict[str, Any]]:
    """JSON-friendly suite descriptors for discover."""
    out: list[dict[str, Any]] = []
    for suite in suites:
        out.append(
            {
                "id": suite.id,
                "runner": suite.runner,
                "extensions": [
                    {
                        "id": ext.id,
                        "name": ext.name,
                        "path": ext.source_rel,
                    }
                    for ext in suite.extensions
                ],
            }
        )
    return out


def extension_source_dirs(
    root: Path,
    suites: list[SuiteRef],
) -> list[tuple[ExtensionRef, Path]]:
    """Absolute source directories for suite extensions (xml layout)."""
    result: list[tuple[ExtensionRef, Path]] = []
    seen: set[str] = set()
    for suite in suites:
        for ext in suite.extensions:
            if ext.id in seen:
                continue
            seen.add(ext.id)
            if not ext.source_rel:
                continue
            path = (root / ext.source_rel).resolve()
            result.append((ext, path))
    return result


def target_summary(target: ResolvedTarget) -> tuple[str, str | None]:
    return target.config_id, target.runtime_id
