"""CLI tests for 1c-dev test (ADR-029 / #124)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from cli.main import app
from core.exit_codes import (
    CHECK_FAILURE,
    ENV_UNAVAILABLE,
    PROJECT_ERROR,
    SUCCESS,
    TEST_FAILURE,
)
from core.test.result import TestResult as ApiTestResult

runner = CliRunner()


def _result(
    *,
    status: str = "ok",
    exit_code: int = SUCCESS,
    **kwargs: Any,
) -> ApiTestResult:
    return ApiTestResult(status=status, exit_code=exit_code, **kwargs)  # type: ignore[arg-type]


def test_cli_test_help() -> None:
    result = runner.invoke(app, ["test", "--help"])
    assert result.exit_code == 0
    assert "discover" in result.stdout
    assert "list" in result.stdout
    assert "run" in result.stdout
    assert "report" in result.stdout


def test_cli_test_discover_json(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_discover(
        start: Path | None = None,
        *,
        config_id: str | None = None,
        runtime_id: str | None = None,
        suite_id: str | None = None,
    ) -> ApiTestResult:
        captured.update(
            {
                "start": start,
                "config_id": config_id,
                "runtime_id": runtime_id,
                "suite_id": suite_id,
            }
        )
        return _result(
            status="ok",
            exit_code=SUCCESS,
            config_id=config_id or "main",
            suite_ids=["unit"],
            modules=[{"name": "DemoTests", "extension": "Tests1"}],
        )

    monkeypatch.setattr("cli.test.discover_tests", fake_discover)
    result = runner.invoke(
        app,
        ["test", "discover", "--config", "main", "--suite", "unit", "--output", "json"],
    )
    assert result.exit_code == SUCCESS
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["exitCode"] == SUCCESS
    assert payload["modules"][0]["name"] == "DemoTests"
    assert captured["config_id"] == "main"
    assert captured["suite_id"] == "unit"


def test_cli_test_list_json(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_list(*_args: Any, **_kwargs: Any) -> ApiTestResult:
        return _result(
            status="ok",
            exit_code=SUCCESS,
            tests=[{"name": "DemoTests.Ok", "status": "unknown"}],
            source="discover",
            incomplete=True,
            total=1,
        )

    monkeypatch.setattr("cli.test.list_tests", fake_list)
    result = runner.invoke(app, ["test", "list", "--output", "json"])
    assert result.exit_code == SUCCESS
    payload = json.loads(result.stdout)
    assert payload["source"] == "discover"
    assert payload["incomplete"] is True
    assert payload["tests"][0]["name"] == "DemoTests.Ok"


def test_cli_test_run_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_run(
        start: Path | None = None,
        *,
        config_id: str | None = None,
        runtime_id: str | None = None,
        suite_id: str | None = None,
        **_kwargs: Any,
    ) -> ApiTestResult:
        captured.update(
            {
                "config_id": config_id,
                "runtime_id": runtime_id,
                "suite_id": suite_id,
            }
        )
        return _result(
            status="passed",
            exit_code=SUCCESS,
            passed=2,
            failed=0,
            error=0,
            skipped=0,
            total=2,
            tests=[
                {"name": "DemoTests.Ok", "status": "passed"},
                {"name": "DemoTests.Also", "status": "passed"},
            ],
        )

    monkeypatch.setattr("cli.test.run_tests", fake_run)
    result = runner.invoke(
        app,
        [
            "test",
            "run",
            "--config",
            "main",
            "--runtime",
            "dev",
            "--suite",
            "unit",
            "--output",
            "json",
        ],
    )
    assert result.exit_code == SUCCESS
    payload = json.loads(result.stdout)
    assert payload["status"] == "passed"
    assert payload["exitCode"] == SUCCESS
    assert payload["passed"] == 2
    assert captured == {
        "config_id": "main",
        "runtime_id": "dev",
        "suite_id": "unit",
    }


def test_cli_test_run_failure_exit_5(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*_args: Any, **_kwargs: Any) -> ApiTestResult:
        return _result(
            status="failed",
            exit_code=TEST_FAILURE,
            passed=1,
            failed=1,
            error=0,
            skipped=0,
            total=2,
            tests=[
                {"name": "DemoTests.Ok", "status": "passed"},
                {"name": "DemoTests.Bad", "status": "failed"},
            ],
        )

    monkeypatch.setattr("cli.test.run_tests", fake_run)
    result = runner.invoke(app, ["test", "run", "--output", "json"])
    assert result.exit_code == TEST_FAILURE
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["exitCode"] == TEST_FAILURE
    assert payload["failed"] == 1


def test_cli_test_run_empty_exit_1(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*_args: Any, **_kwargs: Any) -> ApiTestResult:
        return _result(status="empty", exit_code=CHECK_FAILURE, total=0, passed=0, failed=0)

    monkeypatch.setattr("cli.test.run_tests", fake_run)
    result = runner.invoke(app, ["test", "run", "--output", "json"])
    assert result.exit_code == CHECK_FAILURE
    payload = json.loads(result.stdout)
    assert payload["exitCode"] == CHECK_FAILURE


def test_cli_test_run_one(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_one(
        test_id: str,
        start: Path | None = None,
        *,
        config_id: str | None = None,
        runtime_id: str | None = None,
        suite_id: str | None = None,
        **_kwargs: Any,
    ) -> ApiTestResult:
        captured["test_id"] = test_id
        captured["suite_id"] = suite_id
        return _result(
            status="passed",
            exit_code=SUCCESS,
            passed=1,
            failed=0,
            total=1,
            tests=[{"name": test_id, "status": "passed"}],
        )

    monkeypatch.setattr("cli.test.run_one_test", fake_one)
    result = runner.invoke(
        app,
        ["test", "run", "DemoTests.Ok", "--suite", "unit", "--output", "json"],
    )
    assert result.exit_code == SUCCESS
    payload = json.loads(result.stdout)
    assert payload["tests"][0]["name"] == "DemoTests.Ok"
    assert captured["test_id"] == "DemoTests.Ok"
    assert captured["suite_id"] == "unit"


def test_cli_test_run_one_error_exit_5(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_one(*_args: Any, **_kwargs: Any) -> ApiTestResult:
        return _result(
            status="error",
            exit_code=TEST_FAILURE,
            passed=0,
            failed=0,
            error=1,
            total=1,
        )

    monkeypatch.setattr("cli.test.run_one_test", fake_one)
    result = runner.invoke(app, ["test", "run", "DemoTests.Boom", "--output", "json"])
    assert result.exit_code == TEST_FAILURE


def test_cli_test_run_project_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*_args: Any, **_kwargs: Any) -> ApiTestResult:
        return _result(
            status="failed",
            exit_code=PROJECT_ERROR,
            diagnostics=[
                {
                    "severity": "error",
                    "message": "нет suites",
                    "code": "1CT102",
                    "source": "test",
                }
            ],
        )

    monkeypatch.setattr("cli.test.run_tests", fake_run)
    result = runner.invoke(app, ["test", "run", "--output", "json"])
    assert result.exit_code == PROJECT_ERROR
    payload = json.loads(result.stdout)
    assert payload["diagnostics"][0]["code"] == "1CT102"


def test_cli_test_run_env_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*_args: Any, **_kwargs: Any) -> ApiTestResult:
        return _result(
            status="failed",
            exit_code=ENV_UNAVAILABLE,
            diagnostics=[
                {
                    "severity": "error",
                    "message": "1cv8 не найден",
                    "code": "1CT107",
                    "source": "platform",
                }
            ],
        )

    monkeypatch.setattr("cli.test.run_tests", fake_run)
    result = runner.invoke(app, ["test", "run", "--output", "json"])
    assert result.exit_code == ENV_UNAVAILABLE


def test_cli_test_report_json(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_report(*_args: Any, **_kwargs: Any) -> ApiTestResult:
        return _result(
            status="failed",
            exit_code=TEST_FAILURE,
            passed=1,
            failed=1,
            total=2,
            source="report",
        )

    monkeypatch.setattr("cli.test.report_tests", fake_report)
    result = runner.invoke(app, ["test", "report", "--output", "json"])
    assert result.exit_code == TEST_FAILURE
    payload = json.loads(result.stdout)
    assert payload["source"] == "report"
    assert payload["exitCode"] == TEST_FAILURE


def test_cli_test_run_text_output(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*_args: Any, **_kwargs: Any) -> ApiTestResult:
        return _result(
            status="passed",
            exit_code=SUCCESS,
            config_id="main",
            suite_ids=["unit"],
            passed=1,
            failed=0,
            total=1,
        )

    monkeypatch.setattr("cli.test.run_tests", fake_run)
    result = runner.invoke(app, ["test", "run", "--output", "text"])
    assert result.exit_code == SUCCESS
    assert "status: passed" in result.stdout
    assert "counts: passed=1" in result.stdout
