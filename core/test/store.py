"""Persist last Test API result under ``.1c-dev/test/`` (ADR-029 / #123)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.diagnostics import Diagnostic, error
from core.test.constants import (
    CODE_NO_RUN_META,
    CODE_STORE,
    LAST_RESULT_NAME,
    RUN_META_NAME,
    TEST_DIR_NAME,
)
from core.test.result import TestResult


def test_home(root: Path) -> Path:
    """``.1c-dev/test`` under project scope root."""
    return root / TEST_DIR_NAME


def last_result_path(root: Path) -> Path:
    """Path to structured last-result JSON."""
    return test_home(root) / LAST_RESULT_NAME


def run_meta_path(root: Path) -> Path:
    """Path to detach-run metadata (``test.run --debug`` / #147)."""
    return test_home(root) / RUN_META_NAME


def work_dir(root: Path) -> Path:
    """Working directory for YaXUnit artifacts (cfg / jUnit / logs)."""
    return test_home(root) / "work"


def save_last_result(root: Path, result: TestResult) -> Path:
    """Write ``last-result.json`` from ``TestResult.to_payload()``."""
    path = last_result_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = result.to_payload()
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def save_run_meta(root: Path, meta: dict[str, Any]) -> Path:
    """Write ``run.meta.json`` for a detach debug test run."""
    path = run_meta_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def load_run_meta(root: Path) -> tuple[dict[str, Any] | None, list[Diagnostic]]:
    """Load detach-run metadata, or diagnostics if missing/corrupt."""
    path = run_meta_path(root)
    if not path.is_file():
        return None, [
            error(
                f"Нет активного detach-прогона: {TEST_DIR_NAME}/{RUN_META_NAME}",
                code=CODE_NO_RUN_META,
                source="test",
                suggestion="Сначала выполните test.run --debug (или test.runOne --debug)",
            )
        ]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [
            error(
                f"Не удалось прочитать run.meta.json: {exc}",
                code=CODE_STORE,
                file=str(path.name),
                source="test",
            )
        ]
    if not isinstance(data, dict):
        return None, [
            error(
                "run.meta.json имеет неверный формат",
                code=CODE_STORE,
                file=str(path.name),
                source="test",
            )
        ]
    return data, []


def clear_run_meta(root: Path) -> None:
    """Remove ``run.meta.json`` after ``test.wait`` (or teardown)."""
    path = run_meta_path(root)
    path.unlink(missing_ok=True)


def load_last_result_payload(root: Path) -> tuple[dict[str, Any] | None, list[Diagnostic]]:
    """Load last structured result payload, or diagnostics if missing/corrupt."""
    path = last_result_path(root)
    if not path.is_file():
        return None, [
            error(
                f"Последний отчёт тестов не найден: {TEST_DIR_NAME}/{LAST_RESULT_NAME}",
                code=CODE_STORE,
                source="test",
                suggestion="Сначала выполните test.run / test.runOne",
            )
        ]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [
            error(
                f"Не удалось прочитать последний отчёт тестов: {exc}",
                code=CODE_STORE,
                file=str(path.name),
                source="test",
            )
        ]
    if not isinstance(data, dict):
        return None, [
            error(
                "Последний отчёт тестов имеет неверный формат",
                code=CODE_STORE,
                file=str(path.name),
                source="test",
            )
        ]
    return data, []
