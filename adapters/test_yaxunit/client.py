"""Subprocess runner for YaXUnit ``RunUnitTests`` via ``1cv8 ENTERPRISE`` (ADR-029)."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from adapters.test_yaxunit.config import YaxunitConfigError, build_run_config
from adapters.test_yaxunit.constants import (
    CODE_ENV,
    CODE_IB_MISSING,
    CODE_NO_REPORT,
    CODE_ONECV8_MISSING,
    CODE_RUN_FAILED,
    CODE_TIMEOUT,
    DEFAULT_TIMEOUT_SEC,
)
from adapters.test_yaxunit.junit import (
    TestRunResult,
    YaxunitParseError,
    parse_junit,
    read_yaxunit_exit_code,
)
from core.diagnostics import Diagnostic
from core.diagnostics import error as diag_error


class YaxunitError(Exception):
    """YaXUnit adapter failure with structured diagnostics."""

    def __init__(
        self,
        message: str,
        *,
        code: str = CODE_RUN_FAILED,
        diagnostics: list[Diagnostic] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.diagnostics = diagnostics or [
            diag_error(message, code=code, source="test_yaxunit")
        ]


@dataclass(frozen=True)
class ProcessRunResult:
    """Raw result of one ``1cv8`` / ``xvfb-run`` invocation."""

    returncode: int
    argv: list[str]
    timed_out: bool = False


@dataclass(frozen=True)
class ProcessSpawnResult:
    """Detached ``1cv8`` spawn (debug path / ADR-031 §6a)."""

    pid: int
    argv: list[str]


@dataclass(frozen=True)
class SpawnedUnitTests:
    """Work-dir artifacts + pid after detach spawn (before jUnit exists)."""

    pid: int
    argv: tuple[str, ...]
    work_dir: Path
    report_path: Path
    exit_code_path: Path
    log_path: Path
    out_log_path: Path
    config_path: Path


RunFn = Callable[[list[str], float], ProcessRunResult]
SpawnFn = Callable[[list[str]], ProcessSpawnResult]


def build_enterprise_run_argv(
    onecv8: Path,
    *,
    ib_path: Path,
    config_path: Path,
    out_log: Path,
    use_xvfb: bool | None = None,
    debug: bool = False,
    debugger_url: str | None = None,
) -> list[str]:
    """
    Build argv for thick client ``ENTERPRISE`` + ``/CRunUnitTests=<cfg>``.

    When ``use_xvfb`` is None, wrap with ``xvfb-run -a`` if ``DISPLAY`` is unset
    and ``xvfb-run`` is on PATH (headless CI / agent). With ``debug=True`` xvfb
    must not be used (caller passes ``use_xvfb=False``).
    """
    argv = [
        str(onecv8),
        "ENTERPRISE",
        f"/F{ib_path.resolve()}",
    ]
    if debug:
        if debugger_url:
            argv.extend(
                [
                    "/Debug",
                    "-http",
                    "-attach",
                    f'/DebuggerURL"{debugger_url}"',
                ]
            )
        else:
            argv.append("/Debug")
    argv.extend(
        [
            "/DisableStartupDialogs",
            "/DisableStartupMessages",
            "/DisableSplash",
            "/L",
            "ru",
            "/Out",
            str(out_log.resolve()),
            f"/CRunUnitTests={config_path.resolve()}",
        ]
    )
    if use_xvfb is None:
        use_xvfb = not bool(os.environ.get("DISPLAY")) and shutil.which("xvfb-run") is not None
    if use_xvfb:
        xvfb = shutil.which("xvfb-run")
        if xvfb is None:
            raise YaxunitError(
                "DISPLAY не задан и xvfb-run не найден",
                code=CODE_ENV,
                diagnostics=[
                    diag_error(
                        "DISPLAY не задан и xvfb-run не найден",
                        code=CODE_ENV,
                        source="test_yaxunit",
                        suggestion="задайте DISPLAY или установите xvfb-run",
                    )
                ],
            )
        argv = [xvfb, "-a", *argv]
    return argv


def _popen_session(args: list[str]) -> subprocess.Popen[Any]:
    """Start ``1cv8`` in a new session / process group (for killpg on timeout)."""
    if sys.platform == "win32":
        creationflags = 0x00000200  # CREATE_NEW_PROCESS_GROUP
        return subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creationflags,
        )
    return subprocess.Popen(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        start_new_session=True,
    )


def default_spawn_detach(argv: list[str]) -> ProcessSpawnResult:
    """Detach-start ``1cv8``; caller waits for exit via pid poll (``test.wait``)."""
    args = list(argv)
    proc = _popen_session(args)
    return ProcessSpawnResult(pid=proc.pid, argv=args)


def default_run(argv: list[str], timeout: float) -> ProcessRunResult:
    """
    Run process in a new session; on timeout kill the process group.

    Spike: ``subprocess.run(timeout=…)`` alone leaves orphan ``1cv8`` /
    ``Xvfb`` — always ``start_new_session`` + ``killpg``.
    """
    args = list(argv)
    proc = _popen_session(args)
    try:
        returncode = proc.wait(timeout=timeout)
        return ProcessRunResult(returncode=returncode, argv=args, timed_out=False)
    except subprocess.TimeoutExpired:
        if sys.platform == "win32":
            proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
        else:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        return ProcessRunResult(returncode=124, argv=args, timed_out=True)


def _require_onecv8(onecv8: Path) -> None:
    if not onecv8.is_file() and not onecv8.exists():
        raise YaxunitError(
            f"1cv8 не найден: {onecv8}",
            code=CODE_ONECV8_MISSING,
            diagnostics=[
                diag_error(
                    f"1cv8 не найден: {onecv8}",
                    code=CODE_ONECV8_MISSING,
                    source="test_yaxunit",
                )
            ],
        )


def _require_ib(ib_path: Path) -> None:
    if not ib_path.exists():
        raise YaxunitError(
            f"информационная база не найдена: {ib_path}",
            code=CODE_IB_MISSING,
            diagnostics=[
                diag_error(
                    f"информационная база не найдена: {ib_path}",
                    code=CODE_IB_MISSING,
                    source="test_yaxunit",
                    suggestion="выполните 1c-dev build",
                )
            ],
        )


def prepare_work_dir(work_dir: Path) -> dict[str, Path]:
    """Create work dir and return standard artifact paths."""
    work_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "config": work_dir / "cfg.json",
        "report": work_dir / "junit.xml",
        "exit_code": work_dir / "exit-code.txt",
        "log": work_dir / "yaxunit.log",
        "out_log": work_dir / "out.log",
    }
    for path in paths.values():
        path.unlink(missing_ok=True)
    return paths


def _prepare_run_paths(
    work_dir: Path,
    *,
    extensions: Sequence[str],
    modules: Sequence[str] | None = None,
    suites: Sequence[str] | None = None,
    tests: Sequence[str] | None = None,
    tags: Sequence[str] | None = None,
    contexts: Sequence[str] | None = None,
) -> dict[str, Path]:
    """Write YaXUnit cfg into ``work_dir``; return artifact paths."""
    try:
        paths = prepare_work_dir(work_dir)
        cfg = build_run_config(
            report_path=paths["report"],
            exit_code_path=paths["exit_code"],
            log_path=paths["log"],
            extensions=extensions,
            modules=modules,
            suites=suites,
            tests=tests,
            tags=tags,
            contexts=contexts,
        )
    except YaxunitConfigError as exc:
        raise YaxunitError(
            exc.message,
            code=exc.code,
            diagnostics=[
                diag_error(exc.message, code=exc.code, source="test_yaxunit")
            ],
        ) from exc

    paths["config"].write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return paths


def _require_display_or_xvfb(*, use_xvfb: bool | None, debug: bool) -> None:
    if debug:
        if not os.environ.get("DISPLAY") and sys.platform != "win32":
            raise YaxunitError(
                "DISPLAY не задан (нужен для test.run --debug)",
                code=CODE_ENV,
                diagnostics=[
                    diag_error(
                        "DISPLAY не задан (нужен для test.run --debug)",
                        code=CODE_ENV,
                        source="test_yaxunit",
                        suggestion=(
                            "задайте DISPLAY; xvfb-run с --debug не используется"
                        ),
                    )
                ],
            )
        return
    if use_xvfb is None and not os.environ.get("DISPLAY") and shutil.which("xvfb-run") is None:
        raise YaxunitError(
            "DISPLAY не задан и xvfb-run не найден",
            code=CODE_ENV,
            diagnostics=[
                diag_error(
                    "DISPLAY не задан и xvfb-run не найден",
                    code=CODE_ENV,
                    source="test_yaxunit",
                    suggestion="задайте DISPLAY или установите xvfb-run",
                )
            ],
        )


def collect_unit_tests_result(
    *,
    report_path: Path,
    exit_code_path: Path,
    log_path: Path,
    out_log_path: Path,
    process_exit_code: int | None = None,
    argv: Sequence[str] | None = None,
    details_limit: int | None = None,
) -> TestRunResult:
    """Parse jUnit after ``1cv8`` exit (blocking run or ``test.wait``)."""
    if not report_path.is_file():
        rc = 0 if process_exit_code is None else process_exit_code
        hint = _no_report_hint(log_path, out_log_path, rc)
        raise YaxunitError(
            hint,
            code=CODE_NO_REPORT if rc == 0 else CODE_RUN_FAILED,
            diagnostics=[
                diag_error(
                    hint,
                    code=CODE_NO_REPORT if rc == 0 else CODE_RUN_FAILED,
                    source="test_yaxunit",
                )
            ],
        )

    parse_kwargs: dict[str, Any] = {}
    if details_limit is not None:
        parse_kwargs["details_limit"] = details_limit
    try:
        result = parse_junit(report_path, **parse_kwargs)
    except YaxunitParseError as exc:
        raise YaxunitError(
            exc.message,
            code=exc.code,
            diagnostics=[
                diag_error(exc.message, code=exc.code, source="test_yaxunit")
            ],
        ) from exc

    yax_code = read_yaxunit_exit_code(exit_code_path)
    return TestRunResult(
        status=result.status,
        passed=result.passed,
        failed=result.failed,
        error=result.error,
        skipped=result.skipped,
        total=result.total,
        duration_sec=result.duration_sec,
        tests=result.tests,
        report_path=result.report_path,
        process_exit_code=process_exit_code,
        yaxunit_exit_code=yax_code,
        timed_out=False,
        properties=result.properties,
        argv=tuple(argv or ()),
    )


def spawn_unit_tests(
    onecv8: Path,
    *,
    ib_path: Path,
    work_dir: Path,
    extensions: Sequence[str],
    modules: Sequence[str] | None = None,
    suites: Sequence[str] | None = None,
    tests: Sequence[str] | None = None,
    tags: Sequence[str] | None = None,
    contexts: Sequence[str] | None = None,
    debug: bool = False,
    debugger_url: str | None = None,
    spawn: SpawnFn | None = None,
) -> SpawnedUnitTests:
    """
    Write cfg and detach-spawn ``1cv8`` with optional HTTP ``/Debug`` (no wait).

    Caller arms debug targets, then ``test.wait`` → ``collect_unit_tests_result``.
    Always forces ``use_xvfb=False`` when ``debug=True``.
    """
    _require_onecv8(onecv8)
    _require_ib(ib_path)
    _require_display_or_xvfb(use_xvfb=False if debug else None, debug=debug)

    paths = _prepare_run_paths(
        work_dir,
        extensions=extensions,
        modules=modules,
        suites=suites,
        tests=tests,
        tags=tags,
        contexts=contexts,
    )
    argv = build_enterprise_run_argv(
        onecv8,
        ib_path=ib_path,
        config_path=paths["config"],
        out_log=paths["out_log"],
        use_xvfb=False if debug else None,
        debug=debug,
        debugger_url=debugger_url,
    )
    spawner = spawn or default_spawn_detach
    spawned = spawner(argv)
    return SpawnedUnitTests(
        pid=spawned.pid,
        argv=tuple(spawned.argv),
        work_dir=work_dir.resolve(),
        report_path=paths["report"],
        exit_code_path=paths["exit_code"],
        log_path=paths["log"],
        out_log_path=paths["out_log"],
        config_path=paths["config"],
    )


def run_unit_tests(
    onecv8: Path,
    *,
    ib_path: Path,
    work_dir: Path,
    extensions: Sequence[str],
    modules: Sequence[str] | None = None,
    suites: Sequence[str] | None = None,
    tests: Sequence[str] | None = None,
    tags: Sequence[str] | None = None,
    contexts: Sequence[str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SEC,
    use_xvfb: bool | None = None,
    details_limit: int | None = None,
    debug: bool = False,
    debugger_url: str | None = None,
    run: RunFn | None = None,
) -> TestRunResult:
    """
    Write RunUnitTests JSON, launch ``1cv8``, parse jUnit → ``TestRunResult``.

    Process return code is **not** the source of truth for test failures
    (YaXUnit often exits 0); rely on jUnit / ``exitCode`` file.

    Raises ``YaxunitError`` on launch / environment / missing-report failures.
    Inject ``run`` to mock subprocess in unit tests.
    """
    _require_onecv8(onecv8)
    _require_ib(ib_path)
    _require_display_or_xvfb(use_xvfb=use_xvfb, debug=debug)

    paths = _prepare_run_paths(
        work_dir,
        extensions=extensions,
        modules=modules,
        suites=suites,
        tests=tests,
        tags=tags,
        contexts=contexts,
    )

    effective_xvfb = False if debug else use_xvfb
    argv = build_enterprise_run_argv(
        onecv8,
        ib_path=ib_path,
        config_path=paths["config"],
        out_log=paths["out_log"],
        use_xvfb=effective_xvfb,
        debug=debug,
        debugger_url=debugger_url,
    )

    runner = run or default_run
    proc = runner(argv, timeout)

    if proc.timed_out:
        raise YaxunitError(
            f"таймаут RunUnitTests ({timeout:g}s)",
            code=CODE_TIMEOUT,
            diagnostics=[
                diag_error(
                    f"таймаут RunUnitTests ({timeout:g}s)",
                    code=CODE_TIMEOUT,
                    source="test_yaxunit",
                )
            ],
        )

    return collect_unit_tests_result(
        report_path=paths["report"],
        exit_code_path=paths["exit_code"],
        log_path=paths["log"],
        out_log_path=paths["out_log"],
        process_exit_code=proc.returncode,
        argv=proc.argv,
        details_limit=details_limit,
    )


def _no_report_hint(log_path: Path, out_log: Path, returncode: int) -> str:
    parts = [f"jUnit-отчёт не создан (process exit={returncode})"]
    for label, path in (("yaxunit.log", log_path), ("out.log", out_log)):
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                continue
            if text:
                snippet = text.splitlines()[-1][:200]
                parts.append(f"{label}: {snippet}")
    if returncode == 255:
        parts.append("возможно нет DISPLAY (ENV_UNAVAILABLE)")
    return "; ".join(parts)


__all__ = [
    "CODE_ENV",
    "CODE_IB_MISSING",
    "CODE_NO_REPORT",
    "CODE_ONECV8_MISSING",
    "CODE_RUN_FAILED",
    "CODE_TIMEOUT",
    "ProcessRunResult",
    "ProcessSpawnResult",
    "RunFn",
    "SpawnFn",
    "SpawnedUnitTests",
    "YaxunitError",
    "build_enterprise_run_argv",
    "collect_unit_tests_result",
    "default_run",
    "default_spawn_detach",
    "prepare_work_dir",
    "run_unit_tests",
    "spawn_unit_tests",
]
