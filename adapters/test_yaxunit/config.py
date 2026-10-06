"""YaXUnit RunUnitTests JSON config and filter helpers (ADR-029)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from adapters.test_yaxunit.constants import (
    CODE_FILTER,
    DEFAULT_LOG_LEVEL,
    REPORT_FORMAT_JUNIT,
    RUNNER_EXTENSION_NAME,
)

# Module.Method or Module.Method.Context (1–3 dotted segments; Context may be Cyrillic).
_TEST_PATH_RE = re.compile(r"^[^.\s]+(?:\.[^.\s]+){1,2}$")


class YaxunitConfigError(ValueError):
    """Invalid RunUnitTests filter / config input."""

    def __init__(self, message: str, *, code: str = CODE_FILTER) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def prepare_filter_extensions(
    extension_names: Sequence[str],
    *,
    runner_names: Sequence[str] = (RUNNER_EXTENSION_NAME,),
) -> list[str]:
    """
    Build explicit ``filter.extensions`` without runner-extension (YAXUNIT).

    Deduplicates case-insensitively, preserves first-seen order. Raises if the
    resulting list is empty (ADR-029: never run with an empty extensions filter).
    """
    excluded = {n.casefold() for n in runner_names if n.strip()}
    result: list[str] = []
    seen: set[str] = set()
    for raw in extension_names:
        name = raw.strip()
        if not name:
            continue
        key = name.casefold()
        if key in excluded or key in seen:
            continue
        seen.add(key)
        result.append(name)
    if not result:
        raise YaxunitConfigError(
            "filter.extensions пуст: укажите хотя бы одно test-extension "
            f"(без {RUNNER_EXTENSION_NAME})",
            code=CODE_FILTER,
        )
    return result


def validate_test_path(path: str) -> str:
    """
    Validate ``filter.tests`` entry ``Module.Method[.Context]``.

    Invalid paths hang YaXUnit (spike §4) — reject before launch.
    """
    cleaned = path.strip()
    if not cleaned or not _TEST_PATH_RE.fullmatch(cleaned):
        raise YaxunitConfigError(
            f"некорректный путь теста {path!r}: ожидается Module.Method[.Context]",
            code=CODE_FILTER,
        )
    return cleaned


def build_run_config(
    *,
    report_path: Path,
    exit_code_path: Path,
    log_path: Path,
    extensions: Sequence[str],
    modules: Sequence[str] | None = None,
    suites: Sequence[str] | None = None,
    tests: Sequence[str] | None = None,
    tags: Sequence[str] | None = None,
    contexts: Sequence[str] | None = None,
    log_level: str = DEFAULT_LOG_LEVEL,
) -> dict[str, Any]:
    """
    Build YaXUnit JSON config for ``/CRunUnitTests=<cfg.json>``.

    Always sets ``closeAfterTests=true``, ``showReport=false``, ``reportFormat=jUnit``.
    """
    filter_ext = prepare_filter_extensions(extensions)
    flt: dict[str, Any] = {"extensions": filter_ext}
    if modules:
        flt["modules"] = [m.strip() for m in modules if m.strip()]
    if suites:
        flt["suites"] = [s.strip() for s in suites if s.strip()]
    if tests:
        flt["tests"] = [validate_test_path(t) for t in tests]
    if tags:
        flt["tags"] = [t.strip() for t in tags if t.strip()]
    if contexts:
        flt["contexts"] = [c.strip() for c in contexts if c.strip()]

    return {
        "filter": flt,
        "reportFormat": REPORT_FORMAT_JUNIT,
        "reportPath": str(report_path.resolve()),
        "exitCode": str(exit_code_path.resolve()),
        "closeAfterTests": True,
        "showReport": False,
        "logging": {
            "file": str(log_path.resolve()),
            "console": False,
            "level": log_level,
        },
    }


def test_case_id(*, module: str, test: str, context: str | None) -> str:
    """Build runOne-style id ``Module.Method[.Context]``."""
    if context:
        return f"{module}.{test}.{context}"
    return f"{module}.{test}"
