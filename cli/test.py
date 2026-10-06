"""CLI: 1c-dev test … (ADR-029 / #124)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from cli.options import ConfigOption, RuntimeOption
from cli.output import OutputFormat, OutputOption, resolve_output
from core.test import (
    TestResult,
    discover_tests,
    list_tests,
    report_tests,
    run_one_test,
    run_tests,
)

app = typer.Typer(
    name="test",
    help="Test API: discover / list / run / report (YAxUnit).",
    add_completion=False,
    no_args_is_help=True,
)

NoRunnerEnsureOption = Annotated[
    bool,
    typer.Option(
        "--no-runner-ensure",
        help=(
            "Не подключать YAXUNIT из cache и не снимать safe-mode перед прогоном "
            "(ИБ уже подготовлена)."
        ),
    ),
]

SuiteOption = Annotated[
    str | None,
    typer.Option(
        "--suite",
        help="Id suite из configurations[].tests[] (без флага — все suites).",
    ),
]


def _emit(payload: dict[str, Any], output: OutputFormat, *, text_lines: list[str]) -> None:
    if output is OutputFormat.json:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for line in text_lines:
            typer.echo(line)


def _diag_lines(result: TestResult) -> list[str]:
    lines: list[str] = []
    for diag in result.diagnostics:
        code = diag.get("code", "")
        severity = diag.get("severity", "error")
        prefix = f"[{code}] " if code else ""
        label = "warning" if severity == "warning" else "error"
        lines.append(f"{label}: {prefix}{diag.get('message', '')}")
        suggestion = diag.get("suggestion")
        if suggestion:
            lines.append(f"  → {suggestion}")
    return lines


def _counts_line(result: TestResult) -> str | None:
    if result.total is None and result.passed is None:
        return None
    parts: list[str] = []
    if result.passed is not None:
        parts.append(f"passed={result.passed}")
    if result.failed is not None:
        parts.append(f"failed={result.failed}")
    if result.error is not None:
        parts.append(f"error={result.error}")
    if result.skipped is not None:
        parts.append(f"skipped={result.skipped}")
    if result.total is not None:
        parts.append(f"total={result.total}")
    return "counts: " + ", ".join(parts) if parts else None


def _runner_ensure_lines(info: dict[str, Any]) -> list[str]:
    lines = [f"runnerEnsure: {info.get('status', '')}"]
    if info.get("reason"):
        lines.append(f"  reason: {info['reason']}")
    if info.get("cfePath"):
        pin = f" ({info['pin']})" if info.get("pin") else ""
        lines.append(f"  cfe: {info['cfePath']}{pin}")
    if info.get("loaded"):
        lines.append("  loaded: YAXUNIT")
    steps = info.get("steps") or []
    if steps:
        lines.append("  steps: " + ", ".join(str(step) for step in steps))
    return lines


def _result_text(result: TestResult) -> list[str]:
    lines = [f"status: {result.status}"]
    if result.config_id:
        lines.append(f"config: {result.config_id}")
    if result.runtime_id:
        lines.append(f"runtime: {result.runtime_id}")
    if result.suite_ids:
        lines.append("suites: " + ", ".join(result.suite_ids))
    if result.duration is not None:
        lines.append(f"duration: {result.duration:.3f}s")
    if result.duration_sec is not None:
        lines.append(f"durationSec: {result.duration_sec:.3f}")
    counts = _counts_line(result)
    if counts:
        lines.append(counts)
    if result.source:
        lines.append(f"source: {result.source}")
    if result.incomplete:
        lines.append("incomplete: true")
    if result.report_path:
        lines.append(f"report: {result.report_path}")
    if result.runner_ensure:
        lines.extend(_runner_ensure_lines(result.runner_ensure))
    if result.suites:
        lines.append(f"suitesFound: {len(result.suites)}")
    if result.modules:
        lines.append(f"modules: {len(result.modules)}")
        for mod in result.modules[:20]:
            name = mod.get("name", "")
            ext = mod.get("extension") or mod.get("extensionId") or ""
            suffix = f" ({ext})" if ext else ""
            lines.append(f"  - {name}{suffix}")
        if len(result.modules) > 20:
            lines.append(f"  … +{len(result.modules) - 20} more")
    if result.tests:
        lines.append(f"tests: {len(result.tests)}")
        for case in result.tests[:20]:
            name = case.get("name") or case.get("test") or ""
            status = case.get("status", "")
            lines.append(f"  - {name} [{status}]" if status else f"  - {name}")
        if len(result.tests) > 20:
            lines.append(f"  … +{len(result.tests) - 20} more")
    lines.extend(_diag_lines(result))
    return lines


def finish(result: TestResult, ctx: typer.Context, output: OutputOption) -> None:
    """Emit result (json/text) and exit with ``result.exit_code``."""
    _emit(
        result.to_payload(),
        resolve_output(ctx, output),
        text_lines=_result_text(result),
    )
    raise typer.Exit(code=result.exit_code)


@app.command("discover")
def discover_command(
    ctx: typer.Context,
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    suite: SuiteOption = None,
    output: OutputOption = None,
) -> None:
    """Статический inventory suites / modules (без платформы)."""
    result = discover_tests(
        Path.cwd(),
        config_id=config,
        runtime_id=runtime,
        suite_id=suite,
    )
    finish(result, ctx, output)


@app.command("list")
def list_command(
    ctx: typer.Context,
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    suite: SuiteOption = None,
    output: OutputOption = None,
) -> None:
    """Лучший доступный список тестов (report или discover)."""
    result = list_tests(
        Path.cwd(),
        config_id=config,
        runtime_id=runtime,
        suite_id=suite,
    )
    finish(result, ctx, output)


@app.command("run")
def run_command(
    ctx: typer.Context,
    name: str | None = typer.Argument(
        None,
        help="Один тест Module.Method[.Context]; без аргумента — все выбранные suites.",
    ),
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    suite: SuiteOption = None,
    no_runner_ensure: NoRunnerEnsureOption = False,
    output: OutputOption = None,
) -> None:
    """Прогнать тесты (run) или один тест (runOne). Не вызывает build."""
    if name:
        result = run_one_test(
            name,
            Path.cwd(),
            config_id=config,
            runtime_id=runtime,
            suite_id=suite,
            skip_runner_ensure=no_runner_ensure,
        )
    else:
        result = run_tests(
            Path.cwd(),
            config_id=config,
            runtime_id=runtime,
            suite_id=suite,
            skip_runner_ensure=no_runner_ensure,
        )
    finish(result, ctx, output)


@app.command("report")
def report_command(
    ctx: typer.Context,
    config: ConfigOption = None,
    runtime: RuntimeOption = None,
    output: OutputOption = None,
) -> None:
    """Последний сохранённый structured-отчёт прогона."""
    result = report_tests(
        Path.cwd(),
        config_id=config,
        runtime_id=runtime,
    )
    finish(result, ctx, output)
