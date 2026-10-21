"""Test API orchestration: discover / list / run / runOne / report (ADR-029 / #123)."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from adapters.platform import DiscoveryResult, discover_environment
from adapters.platform_1cv8.process import is_running
from adapters.platform_ibcmd import infobase_exists
from adapters.test_yaxunit import (
    CODE_ENV,
    DEFAULT_TIMEOUT_SEC,
    SpawnedUnitTests,
    TestCaseResult,
    TestRunResult,
    YaxunitConfigError,
    YaxunitError,
    collect_unit_tests_result,
    run_unit_tests,
    spawn_unit_tests,
    validate_test_path,
)
from adapters.test_yaxunit import (
    CODE_IB_MISSING as ADAPTER_IB_MISSING,
)
from adapters.test_yaxunit import (
    CODE_ONECV8_MISSING as ADAPTER_ONECV8_MISSING,
)
from core.diagnostics import Diagnostic, error, warning
from core.exit_codes import SUCCESS
from core.project.constants import HOME_MANIFEST_REL
from core.project.detect import detect_manifest
from core.project.load import load_manifest
from core.project.paths import scope_root_from_manifest
from core.project.resolve import ResolvedTarget, resolve_config_runtime
from core.test.constants import (
    CODE_DEBUG_BP,
    CODE_FILTER,
    CODE_IB_MISSING,
    CODE_NO_REPORT,
    CODE_ONECV8_MISSING,
    CODE_PROJECT,
    CODE_WAIT_TIMEOUT,
    DEFAULT_WAIT_TIMEOUT_SEC,
)
from core.test.discover import discover_modules
from core.test.result import (
    Status,
    TestResult,
    exit_code_for_run_status,
    exit_code_from_diagnostics,
)
from core.test.runner_ensure import RunnerEnsureResult, ensure_yaxunit_runner
from core.test.store import (
    clear_run_meta,
    load_last_result_payload,
    load_run_meta,
    save_last_result,
    save_run_meta,
    work_dir,
)
from core.test.suites import (
    SuiteRef,
    filter_extension_names,
    parse_suites,
    require_supported_runners,
    select_suites,
    suites_payload,
)

RunUnitTestsFn = Callable[..., TestRunResult]
SpawnUnitTestsFn = Callable[..., SpawnedUnitTests]
DiscoverFn = Callable[[], DiscoveryResult]
EnsureRunnerFn = Callable[..., RunnerEnsureResult]
IsAliveFn = Callable[[int], bool]


def _fail(
    *,
    started: float,
    diagnostics: list[Diagnostic],
    root: Path | None = None,
    runtime_path: Path | None = None,
    config_id: str | None = None,
    runtime_id: str | None = None,
    suite_ids: list[str] | None = None,
    runner_ensure: dict[str, Any] | None = None,
) -> TestResult:
    return TestResult(
        status="failed",
        diagnostics=list(diagnostics),
        duration=time.perf_counter() - started,
        root=root,
        runtime_path=runtime_path,
        config_id=config_id,
        runtime_id=runtime_id,
        suite_ids=list(suite_ids or []),
        runner_ensure=runner_ensure,
        exit_code=exit_code_from_diagnostics(diagnostics),
    )


def _ensure_runner_step(
    *,
    root: Path,
    target: ResolvedTarget,
    selected: list[SuiteRef] | None,
    db_path: Path,
    skip: bool,
    discover: DiscoverFn | None,
    ensure_fn: EnsureRunnerFn | None,
) -> RunnerEnsureResult | None:
    """Idempotent YAXUNIT preflight (ADR-029 §7a); ``None`` when skipped by the caller."""
    if skip:
        return None
    ensure = ensure_fn or ensure_yaxunit_runner
    return ensure(
        root=root,
        configuration=target.configuration,
        db_path=db_path,
        suites=selected,
        discover=discover,
    )


def _load_project(
    start: Path,
    *,
    started: float,
    config_id: str | None,
    runtime_id: str | None,
    require_runtime: bool,
) -> tuple[Path, dict[str, Any], ResolvedTarget, TestResult | None]:
    """Return (root, data, target, error_result_or_None)."""
    manifest_path = detect_manifest(start)
    if manifest_path is None:
        return (
            start,
            {},
            ResolvedTarget(
                configuration={},
                runtime=None,
                config_id="",
                runtime_id=None,
                source_rel="",
                source_format=None,
                runtime_rel=None,
                runtime_type=None,
            ),
            _fail(
                started=started,
                diagnostics=[
                    error(
                        f"Файл {HOME_MANIFEST_REL} не найден",
                        code=CODE_PROJECT,
                        source="test",
                        suggestion="Выполните 1c-dev init --type configuration",
                    )
                ],
            ),
        )

    data, load_diags = load_manifest(manifest_path)
    root = scope_root_from_manifest(manifest_path)
    if data is None:
        return (
            root,
            {},
            ResolvedTarget(
                configuration={},
                runtime=None,
                config_id="",
                runtime_id=None,
                source_rel="",
                source_format=None,
                runtime_rel=None,
                runtime_type=None,
            ),
            _fail(
                started=started,
                root=root,
                diagnostics=list(load_diags)
                or [
                    error(
                        "Не удалось прочитать манифест",
                        code=CODE_PROJECT,
                        file=str(manifest_path.name),
                        source="test",
                    )
                ],
            ),
        )

    target, resolve_diags = resolve_config_runtime(
        data,
        config_id=config_id,
        runtime_id=runtime_id,
        require_runtime=require_runtime,
    )
    if target is None:
        return (
            root,
            data,
            ResolvedTarget(
                configuration={},
                runtime=None,
                config_id="",
                runtime_id=None,
                source_rel="",
                source_format=None,
                runtime_rel=None,
                runtime_type=None,
            ),
            _fail(
                started=started,
                root=root,
                diagnostics=list(resolve_diags)
                or [
                    error(
                        "Не удалось разрешить --config/--runtime",
                        code=CODE_PROJECT,
                        source="test",
                    )
                ],
            ),
        )
    return root, data, target, None


def _cases_to_dicts(
    cases: tuple[TestCaseResult, ...] | list[TestCaseResult],
) -> list[dict[str, Any]]:
    return [c.to_dict() for c in cases]


_RESULT_STATUSES = frozenset({"ok", "passed", "failed", "error", "empty", "running"})


def _parse_status(raw: object) -> Status:
    if isinstance(raw, str) and raw in _RESULT_STATUSES:
        return raw  # type: ignore[return-value]
    return "ok"


def _bp_requires_debug(
    *,
    started: float,
    breakpoints: Sequence[str],
    debug: bool,
    root: Path | None = None,
    config_id: str | None = None,
    runtime_id: str | None = None,
) -> TestResult | None:
    bp_raw = [str(x).strip() for x in breakpoints if str(x).strip()]
    if bp_raw and not debug:
        return _fail(
            started=started,
            root=root,
            config_id=config_id,
            runtime_id=runtime_id,
            diagnostics=[
                error(
                    "--bp требует --debug",
                    code=CODE_DEBUG_BP,
                    source="test",
                    suggestion=(
                        "1c-dev test run --debug "
                        "--bp src/cfe/test_ext1/CommonModules/ОМ_Арифметика/Ext/Module.bsl:10"
                    ),
                )
            ],
        )
    return None


def _debug_detach_run(
    *,
    started: float,
    start_path: Path,
    root: Path,
    target: ResolvedTarget,
    suite_ids: list[str],
    db_path: Path,
    onecv8: Path,
    ext_names: list[str],
    tests_filter: list[str] | None,
    ensure: RunnerEnsureResult | None,
    breakpoints: Sequence[str],
    debugger_url: str | None,
    discover: DiscoverFn | None,
    spawn_fn: SpawnUnitTestsFn | None,
    targets_timeout: float,
) -> TestResult:
    """ensure dbgs → BP → spawn detach → arm targets → status running (#147)."""
    from core.debug.ops import (
        await_debug_targets_armed,
        ensure_debug_for_runtime,
        prepare_debug_for_spawn,
    )

    bp_raw = [str(x).strip() for x in breakpoints if str(x).strip()]
    debug_bps: list[dict[str, Any]] = []
    debug_session_id: str | None = None
    resolved_url: str | None = debugger_url
    arm_targets = False

    if bp_raw:
        boot = ensure_debug_for_runtime(
            start_path,
            breakpoints=bp_raw,
            debugger_url=debugger_url,
            config_id=target.config_id,
            runtime_id=target.runtime_id,
            discover=discover,
        )
        if boot.status != "ok":
            return TestResult(
                status="failed",
                duration=time.perf_counter() - started,
                root=root,
                runtime_path=db_path,
                config_id=target.config_id,
                runtime_id=target.runtime_id,
                suite_ids=suite_ids,
                debug_enabled=True,
                debugger_url=boot.debugger_url or boot.url or debugger_url,
                session_id=boot.session_id,
                breakpoints=list(boot.breakpoints),
                runner_ensure=ensure.to_payload() if ensure is not None else None,
                diagnostics=list(boot.diagnostics),
                exit_code=exit_code_from_diagnostics(list(boot.diagnostics)),
            )
        resolved_url = boot.debugger_url or boot.url or debugger_url
        debug_bps = list(boot.breakpoints)
        debug_session_id = boot.session_id
        arm_targets = True
    else:
        from core.debug.state import read_session, resolve_debugger_url

        stored = read_session(root)
        if stored is not None:
            arm_targets = True
            debug_session_id = str(stored.get("sessionId") or "") or None
            raw_bps = stored.get("breakpoints")
            if isinstance(raw_bps, list):
                debug_bps = [bp for bp in raw_bps if isinstance(bp, dict)]
            session_url = stored.get("url")
            if isinstance(session_url, str) and session_url.strip():
                resolved_url = session_url.strip()
        if not resolved_url:
            # Prefer live server / manifest when no session yet.
            from core.project.detect import detect_manifest as _detect
            from core.project.load import load_manifest as _load

            manifest_path = _detect(start_path)
            data: dict[str, Any] = {}
            if manifest_path is not None:
                loaded, _ = _load(manifest_path)
                if isinstance(loaded, dict):
                    data = loaded
            resolved_url = resolve_debugger_url(
                root, data, explicit=debugger_url
            )
        if not arm_targets:
            # No prior session and no --bp: still ensure dbgs + attach before spawn.
            boot = ensure_debug_for_runtime(
                start_path,
                breakpoints=[],
                debugger_url=debugger_url,
                config_id=target.config_id,
                runtime_id=target.runtime_id,
                discover=discover,
            )
            if boot.status != "ok":
                return TestResult(
                    status="failed",
                    duration=time.perf_counter() - started,
                    root=root,
                    runtime_path=db_path,
                    config_id=target.config_id,
                    runtime_id=target.runtime_id,
                    suite_ids=suite_ids,
                    debug_enabled=True,
                    debugger_url=boot.debugger_url or boot.url or debugger_url,
                    session_id=boot.session_id,
                    runner_ensure=ensure.to_payload() if ensure is not None else None,
                    diagnostics=list(boot.diagnostics),
                    exit_code=exit_code_from_diagnostics(list(boot.diagnostics)),
                )
            resolved_url = boot.debugger_url or boot.url or resolved_url
            debug_session_id = boot.session_id
            arm_targets = True

    prepared = prepare_debug_for_spawn(
        start_path,
        config_id=target.config_id,
        runtime_id=target.runtime_id,
    )
    if prepared.status != "ok":
        return TestResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            runtime_path=db_path,
            config_id=target.config_id,
            runtime_id=target.runtime_id,
            suite_ids=suite_ids,
            debug_enabled=True,
            debugger_url=resolved_url,
            session_id=debug_session_id,
            breakpoints=debug_bps,
            runner_ensure=ensure.to_payload() if ensure is not None else None,
            diagnostics=list(prepared.diagnostics),
            exit_code=exit_code_from_diagnostics(list(prepared.diagnostics)),
        )

    spawner = spawn_fn or spawn_unit_tests
    try:
        spawned = spawner(
            onecv8,
            ib_path=db_path,
            work_dir=work_dir(root),
            extensions=ext_names,
            tests=tests_filter,
            debug=True,
            debugger_url=resolved_url,
        )
    except YaxunitError as exc:
        return _fail(
            started=started,
            root=root,
            runtime_path=db_path,
            config_id=target.config_id,
            runtime_id=target.runtime_id,
            suite_ids=suite_ids,
            diagnostics=_map_adapter_error(exc),
            runner_ensure=ensure.to_payload() if ensure is not None else None,
        )

    extra_diags: list[Diagnostic] = []
    if arm_targets:
        armed = await_debug_targets_armed(
            start_path,
            timeout=targets_timeout,
            config_id=target.config_id,
            runtime_id=target.runtime_id,
        )
        if armed.status != "ok":
            extra_diags.extend(armed.diagnostics)
        else:
            extra_diags.extend(armed.diagnostics)

    save_run_meta(
        root,
        {
            "pid": spawned.pid,
            "workDir": str(spawned.work_dir),
            "reportPath": str(spawned.report_path),
            "exitCodePath": str(spawned.exit_code_path),
            "logPath": str(spawned.log_path),
            "outLogPath": str(spawned.out_log_path),
            "configPath": str(spawned.config_path),
            "argv": list(spawned.argv),
            "debug": True,
            "debuggerUrl": resolved_url,
            "sessionId": debug_session_id,
            "suiteIds": suite_ids,
            "configId": target.config_id,
            "runtimeId": target.runtime_id,
            "startedAt": datetime.now(UTC).isoformat(),
        },
    )

    diags: list[Diagnostic] = []
    if ensure is not None:
        diags.extend(ensure.diagnostics)
    diags.extend(extra_diags)

    return TestResult(
        status="running",
        duration=time.perf_counter() - started,
        root=root,
        runtime_path=db_path,
        config_id=target.config_id,
        runtime_id=target.runtime_id,
        suite_ids=suite_ids,
        pid=spawned.pid,
        debug_enabled=True,
        debugger_url=resolved_url,
        session_id=debug_session_id,
        breakpoints=debug_bps,
        runner_ensure=ensure.to_payload() if ensure is not None else None,
        diagnostics=diags,
        exit_code=SUCCESS,
    )


def _parse_duration_sec(payload: dict[str, Any]) -> float | None:
    value = payload.get("durationSec")
    if isinstance(value, int | float):
        return float(value)
    return None


def _result_from_run(
    *,
    started: float,
    root: Path,
    target: ResolvedTarget,
    suite_ids: list[str],
    run: TestRunResult,
    ensure: RunnerEnsureResult | None = None,
) -> TestResult:
    db_path = (
        (root / target.runtime_rel).resolve()
        if target.runtime_rel
        else None
    )
    report_path = str(run.report_path) if run.report_path else None
    status = run.status
    result = TestResult(
        status=status,
        duration=time.perf_counter() - started,
        root=root,
        runtime_path=db_path,
        config_id=target.config_id,
        runtime_id=target.runtime_id,
        suite_ids=suite_ids,
        passed=run.passed,
        failed=run.failed,
        error=run.error,
        skipped=run.skipped,
        total=run.total,
        duration_sec=run.duration_sec,
        tests=_cases_to_dicts(run.tests),
        report_path=report_path,
        runner_ensure=ensure.to_payload() if ensure is not None else None,
        diagnostics=list(ensure.diagnostics) if ensure is not None else [],
        exit_code=exit_code_for_run_status(status, total=run.total),
    )
    save_last_result(root, result)
    return result


def _map_adapter_error(exc: YaxunitError) -> list[Diagnostic]:
    code = exc.code
    if code == ADAPTER_ONECV8_MISSING:
        mapped = CODE_ONECV8_MISSING
    elif code == ADAPTER_IB_MISSING:
        mapped = CODE_IB_MISSING
    elif code == CODE_ENV:
        mapped = CODE_ENV
    else:
        mapped = code
    if exc.diagnostics:
        # Preserve adapter diagnostics but normalize known codes for exit mapping.
        out: list[Diagnostic] = []
        for diag in exc.diagnostics:
            item = dict(diag)
            if item.get("code") == ADAPTER_ONECV8_MISSING:
                item["code"] = CODE_ONECV8_MISSING
            elif item.get("code") == ADAPTER_IB_MISSING:
                item["code"] = CODE_IB_MISSING
            out.append(item)  # type: ignore[arg-type]
        return out
    return [error(exc.message, code=mapped, source="test_yaxunit")]


def discover_tests(
    start: Path | None = None,
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
    suite_id: str | None = None,
) -> TestResult:
    """
    Static inventory: suites / extensions / modules with ``ИсполняемыеСценарии``.

    Does not touch the platform or IB (ADR-029).
    """
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    root, _data, target, err = _load_project(
        start_path,
        started=started,
        config_id=config_id,
        runtime_id=runtime_id,
        require_runtime=False,
    )
    if err is not None:
        return err

    suites, suite_diags = parse_suites(target.configuration)
    if suites is None:
        return _fail(
            started=started,
            root=root,
            config_id=target.config_id,
            runtime_id=target.runtime_id,
            diagnostics=suite_diags,
        )

    selected, select_diags = select_suites(suites, suite_id=suite_id)
    if selected is None:
        return _fail(
            started=started,
            root=root,
            config_id=target.config_id,
            runtime_id=target.runtime_id,
            diagnostics=select_diags,
        )

    modules = discover_modules(root, selected)
    return TestResult(
        status="ok",
        duration=time.perf_counter() - started,
        root=root,
        config_id=target.config_id,
        runtime_id=target.runtime_id,
        suite_ids=[s.id for s in selected],
        suites=suites_payload(selected),
        modules=modules,
        exit_code=SUCCESS,
    )


def list_tests(
    start: Path | None = None,
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
    suite_id: str | None = None,
) -> TestResult:
    """
    Best-effort test list: prefer last ``report``, else discover modules.

    On a clean project the list may be incomplete (ADR-029).
    """
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    root, _data, target, err = _load_project(
        start_path,
        started=started,
        config_id=config_id,
        runtime_id=runtime_id,
        require_runtime=False,
    )
    if err is not None:
        return err

    payload, store_diags = load_last_result_payload(root)
    if payload is not None:
        tests = payload.get("tests")
        if isinstance(tests, list) and tests:
            status = _parse_status(payload.get("status"))
            return TestResult(
                status="ok" if status != "empty" else "empty",
                duration=time.perf_counter() - started,
                root=root,
                config_id=target.config_id,
                runtime_id=target.runtime_id,
                suite_ids=list(payload.get("suiteIds") or []),
                passed=payload.get("passed") if isinstance(payload.get("passed"), int) else None,
                failed=payload.get("failed") if isinstance(payload.get("failed"), int) else None,
                error=payload.get("error") if isinstance(payload.get("error"), int) else None,
                skipped=payload.get("skipped") if isinstance(payload.get("skipped"), int) else None,
                total=payload.get("total") if isinstance(payload.get("total"), int) else len(tests),
                duration_sec=_parse_duration_sec(payload),
                tests=[t for t in tests if isinstance(t, dict)],
                report_path=payload.get("reportPath")
                if isinstance(payload.get("reportPath"), str)
                else None,
                source="report",
                incomplete=False,
                exit_code=SUCCESS,
            )

    suites, suite_diags = parse_suites(target.configuration)
    if suites is None:
        return _fail(
            started=started,
            root=root,
            config_id=target.config_id,
            runtime_id=target.runtime_id,
            diagnostics=suite_diags,
        )
    selected, select_diags = select_suites(suites, suite_id=suite_id)
    if selected is None:
        return _fail(
            started=started,
            root=root,
            config_id=target.config_id,
            runtime_id=target.runtime_id,
            diagnostics=select_diags,
        )

    modules = discover_modules(root, selected)
    tests = [
        {
            "name": m["name"],
            "module": m["name"],
            "extension": m.get("extension"),
            "status": "unknown",
        }
        for m in modules
    ]
    diags: list[Diagnostic] = []
    if store_diags:
        diags.append(
            warning(
                "Точный список тестов недоступен — показаны модули из source (best-effort)",
                code=CODE_NO_REPORT,
                source="test",
                suggestion="Выполните test.run для полного списка из jUnit",
            )
        )
    return TestResult(
        status="ok",
        diagnostics=diags,
        duration=time.perf_counter() - started,
        root=root,
        config_id=target.config_id,
        runtime_id=target.runtime_id,
        suite_ids=[s.id for s in selected],
        modules=modules,
        tests=tests,
        total=len(tests),
        source="discover",
        incomplete=True,
        exit_code=SUCCESS,
    )


def report_tests(
    start: Path | None = None,
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
) -> TestResult:
    """Return the last saved structured test result (``.1c-dev/test/last-result.json``)."""
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    root, _data, target, err = _load_project(
        start_path,
        started=started,
        config_id=config_id,
        runtime_id=runtime_id,
        require_runtime=False,
    )
    if err is not None:
        return err

    payload, store_diags = load_last_result_payload(root)
    if payload is None:
        return _fail(
            started=started,
            root=root,
            config_id=target.config_id,
            runtime_id=target.runtime_id,
            diagnostics=store_diags,
        )

    status = _parse_status(payload.get("status"))
    tests = payload.get("tests")
    runtime_raw = payload.get("runtimePath")
    runtime_path: Path | None = None
    if isinstance(runtime_raw, str) and runtime_raw:
        candidate = Path(runtime_raw)
        runtime_path = (
            candidate if candidate.is_absolute() else (root / runtime_raw).resolve()
        )
    total_raw = payload.get("total")
    total = total_raw if isinstance(total_raw, int) else 0
    exit_raw = payload.get("exitCode")
    return TestResult(
        status=status,
        duration=time.perf_counter() - started,
        root=root,
        runtime_path=runtime_path,
        config_id=payload.get("configId")
        if isinstance(payload.get("configId"), str)
        else target.config_id,
        runtime_id=payload.get("runtimeId")
        if isinstance(payload.get("runtimeId"), str)
        else target.runtime_id,
        suite_ids=[s for s in (payload.get("suiteIds") or []) if isinstance(s, str)],
        passed=payload.get("passed") if isinstance(payload.get("passed"), int) else None,
        failed=payload.get("failed") if isinstance(payload.get("failed"), int) else None,
        error=payload.get("error") if isinstance(payload.get("error"), int) else None,
        skipped=payload.get("skipped") if isinstance(payload.get("skipped"), int) else None,
        total=total if isinstance(total_raw, int) else None,
        duration_sec=_parse_duration_sec(payload),
        tests=[t for t in tests if isinstance(t, dict)] if isinstance(tests, list) else [],
        report_path=payload.get("reportPath")
        if isinstance(payload.get("reportPath"), str)
        else None,
        source="report",
        exit_code=int(exit_raw)
        if isinstance(exit_raw, int)
        else exit_code_for_run_status(status, total=total),
        diagnostics=[],
    )


def run_tests(
    start: Path | None = None,
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
    suite_id: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SEC,
    discover: DiscoverFn | None = None,
    run_unit_tests_fn: RunUnitTestsFn | None = None,
    spawn_unit_tests_fn: SpawnUnitTestsFn | None = None,
    skip_runner_ensure: bool = False,
    ensure_runner_fn: EnsureRunnerFn | None = None,
    debug: bool = False,
    debugger_url: str | None = None,
    breakpoints: Sequence[str] | None = None,
    targets_timeout: float = 15.0,
) -> TestResult:
    """
    Run selected (or all) yaxunit suites in one ``1cv8`` process.

    With ``debug=True``: non-blocking spawn + HTTP ``/Debug`` (ADR-031 §6a);
    use ``debug.wait`` for stops and ``wait_tests`` for jUnit.

    Does **not** call ``build``. Missing IB → clear diagnostic (ADR-029).
    """
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    bp_list = list(breakpoints or [])
    root, _data, target, err = _load_project(
        start_path,
        started=started,
        config_id=config_id,
        runtime_id=runtime_id,
        require_runtime=True,
    )
    if err is not None:
        return err

    bad_bp = _bp_requires_debug(
        started=started,
        breakpoints=bp_list,
        debug=debug,
        root=root,
        config_id=target.config_id,
        runtime_id=target.runtime_id,
    )
    if bad_bp is not None:
        return bad_bp

    suites, suite_diags = parse_suites(target.configuration)
    if suites is None:
        return _fail(
            started=started,
            root=root,
            config_id=target.config_id,
            runtime_id=target.runtime_id,
            diagnostics=suite_diags,
        )
    selected, select_diags = select_suites(suites, suite_id=suite_id)
    if selected is None:
        return _fail(
            started=started,
            root=root,
            config_id=target.config_id,
            runtime_id=target.runtime_id,
            diagnostics=select_diags,
        )
    runner_diags = require_supported_runners(selected)
    if runner_diags:
        return _fail(
            started=started,
            root=root,
            config_id=target.config_id,
            runtime_id=target.runtime_id,
            suite_ids=[s.id for s in selected],
            diagnostics=runner_diags,
        )

    ext_names, filter_diags = filter_extension_names(selected)
    if ext_names is None:
        return _fail(
            started=started,
            root=root,
            config_id=target.config_id,
            runtime_id=target.runtime_id,
            suite_ids=[s.id for s in selected],
            diagnostics=filter_diags,
        )

    if target.runtime_rel is None:
        return _fail(
            started=started,
            root=root,
            config_id=target.config_id,
            diagnostics=[
                error(
                    "Не удалось разрешить путь runtime",
                    code=CODE_PROJECT,
                    source="test",
                )
            ],
        )
    db_path = (root / target.runtime_rel).resolve()
    if not infobase_exists(db_path):
        return _fail(
            started=started,
            root=root,
            runtime_path=db_path,
            config_id=target.config_id,
            runtime_id=target.runtime_id,
            suite_ids=[s.id for s in selected],
            diagnostics=[
                error(
                    f"File IB не найдена: {target.runtime_rel}",
                    code=CODE_IB_MISSING,
                    source="test",
                    suggestion="Сначала выполните 1c-dev build (test.* не собирает ИБ)",
                )
            ],
        )

    discovery = (discover or discover_environment)()
    onecv8 = discovery.onecv8
    if not onecv8.found or onecv8.path is None:
        return _fail(
            started=started,
            root=root,
            runtime_path=db_path,
            config_id=target.config_id,
            runtime_id=target.runtime_id,
            suite_ids=[s.id for s in selected],
            diagnostics=[
                error(
                    "1cv8 не найден",
                    code=CODE_ONECV8_MISSING,
                    source="platform",
                    suggestion="Установите платформу 1С и добавьте 1cv8 в PATH",
                )
            ],
        )

    ensure = _ensure_runner_step(
        root=root,
        target=target,
        selected=selected,
        db_path=db_path,
        skip=skip_runner_ensure,
        discover=discover,
        ensure_fn=ensure_runner_fn,
    )
    if ensure is not None and ensure.failed:
        return _fail(
            started=started,
            root=root,
            runtime_path=db_path,
            config_id=target.config_id,
            runtime_id=target.runtime_id,
            suite_ids=[s.id for s in selected],
            diagnostics=ensure.diagnostics,
            runner_ensure=ensure.to_payload(),
        )

    suite_ids = [s.id for s in selected]
    if debug:
        return _debug_detach_run(
            started=started,
            start_path=start_path,
            root=root,
            target=target,
            suite_ids=suite_ids,
            db_path=db_path,
            onecv8=onecv8.path,
            ext_names=ext_names,
            tests_filter=None,
            ensure=ensure,
            breakpoints=bp_list,
            debugger_url=debugger_url,
            discover=discover,
            spawn_fn=spawn_unit_tests_fn,
            targets_timeout=targets_timeout,
        )

    runner = run_unit_tests_fn or run_unit_tests
    try:
        run_result = runner(
            onecv8.path,
            ib_path=db_path,
            work_dir=work_dir(root),
            extensions=ext_names,
            timeout=timeout,
        )
    except YaxunitError as exc:
        return _fail(
            started=started,
            root=root,
            runtime_path=db_path,
            config_id=target.config_id,
            runtime_id=target.runtime_id,
            suite_ids=suite_ids,
            diagnostics=_map_adapter_error(exc),
            runner_ensure=ensure.to_payload() if ensure is not None else None,
        )

    return _result_from_run(
        started=started,
        root=root,
        target=target,
        suite_ids=suite_ids,
        run=run_result,
        ensure=ensure,
    )


def run_one_test(
    test_id: str,
    start: Path | None = None,
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
    suite_id: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SEC,
    discover: DiscoverFn | None = None,
    run_unit_tests_fn: RunUnitTestsFn | None = None,
    spawn_unit_tests_fn: SpawnUnitTestsFn | None = None,
    skip_runner_ensure: bool = False,
    ensure_runner_fn: EnsureRunnerFn | None = None,
    debug: bool = False,
    debugger_url: str | None = None,
    breakpoints: Sequence[str] | None = None,
    targets_timeout: float = 15.0,
) -> TestResult:
    """
    Run a single test ``Module.Method[.Context]`` via YaXUnit ``filter.tests``.

    With ``debug=True``: same non-blocking HTTP debug path as ``run_tests``.

    Does **not** call ``build``.
    """
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    bp_list = list(breakpoints or [])

    try:
        validated = validate_test_path(test_id)
    except YaxunitConfigError as exc:
        return _fail(
            started=started,
            diagnostics=[
                error(exc.message, code=CODE_FILTER, source="test")
            ],
        )

    root, _data, target, err = _load_project(
        start_path,
        started=started,
        config_id=config_id,
        runtime_id=runtime_id,
        require_runtime=True,
    )
    if err is not None:
        return err

    bad_bp = _bp_requires_debug(
        started=started,
        breakpoints=bp_list,
        debug=debug,
        root=root,
        config_id=target.config_id,
        runtime_id=target.runtime_id,
    )
    if bad_bp is not None:
        return bad_bp

    suites, suite_diags = parse_suites(target.configuration)
    if suites is None:
        return _fail(
            started=started,
            root=root,
            config_id=target.config_id,
            runtime_id=target.runtime_id,
            diagnostics=suite_diags,
        )
    selected, select_diags = select_suites(suites, suite_id=suite_id)
    if selected is None:
        return _fail(
            started=started,
            root=root,
            config_id=target.config_id,
            runtime_id=target.runtime_id,
            diagnostics=select_diags,
        )
    runner_diags = require_supported_runners(selected)
    if runner_diags:
        return _fail(
            started=started,
            root=root,
            config_id=target.config_id,
            runtime_id=target.runtime_id,
            suite_ids=[s.id for s in selected],
            diagnostics=runner_diags,
        )

    # Ambiguous module names across extensions → require --suite (ADR-029 §6.3).
    if suite_id is None and len(selected) > 1:
        module_name = validated.split(".", 1)[0]
        modules = discover_modules(root, selected)
        hits = [m for m in modules if m.get("name") == module_name]
        ext_ids = {m.get("extensionId") for m in hits}
        if len(ext_ids) > 1:
            return _fail(
                started=started,
                root=root,
                config_id=target.config_id,
                runtime_id=target.runtime_id,
                suite_ids=[s.id for s in selected],
                diagnostics=[
                    error(
                        (
                            f"Модуль {module_name!r} встречается в нескольких extension — "
                            "укажите --suite"
                        ),
                        code=CODE_FILTER,
                        source="test",
                        suggestion="Повторите runOne с --suite <id>",
                    )
                ],
            )

    ext_names, filter_diags = filter_extension_names(selected)
    if ext_names is None:
        return _fail(
            started=started,
            root=root,
            config_id=target.config_id,
            runtime_id=target.runtime_id,
            suite_ids=[s.id for s in selected],
            diagnostics=filter_diags,
        )

    if target.runtime_rel is None:
        return _fail(
            started=started,
            root=root,
            config_id=target.config_id,
            diagnostics=[
                error(
                    "Не удалось разрешить путь runtime",
                    code=CODE_PROJECT,
                    source="test",
                )
            ],
        )
    db_path = (root / target.runtime_rel).resolve()
    if not infobase_exists(db_path):
        return _fail(
            started=started,
            root=root,
            runtime_path=db_path,
            config_id=target.config_id,
            runtime_id=target.runtime_id,
            suite_ids=[s.id for s in selected],
            diagnostics=[
                error(
                    f"File IB не найдена: {target.runtime_rel}",
                    code=CODE_IB_MISSING,
                    source="test",
                    suggestion="Сначала выполните 1c-dev build (test.* не собирает ИБ)",
                )
            ],
        )

    discovery = (discover or discover_environment)()
    onecv8 = discovery.onecv8
    if not onecv8.found or onecv8.path is None:
        return _fail(
            started=started,
            root=root,
            runtime_path=db_path,
            config_id=target.config_id,
            runtime_id=target.runtime_id,
            suite_ids=[s.id for s in selected],
            diagnostics=[
                error(
                    "1cv8 не найден",
                    code=CODE_ONECV8_MISSING,
                    source="platform",
                    suggestion="Установите платформу 1С и добавьте 1cv8 в PATH",
                )
            ],
        )

    ensure = _ensure_runner_step(
        root=root,
        target=target,
        selected=selected,
        db_path=db_path,
        skip=skip_runner_ensure,
        discover=discover,
        ensure_fn=ensure_runner_fn,
    )
    if ensure is not None and ensure.failed:
        return _fail(
            started=started,
            root=root,
            runtime_path=db_path,
            config_id=target.config_id,
            runtime_id=target.runtime_id,
            suite_ids=[s.id for s in selected],
            diagnostics=ensure.diagnostics,
            runner_ensure=ensure.to_payload(),
        )

    suite_ids = [s.id for s in selected]
    if debug:
        return _debug_detach_run(
            started=started,
            start_path=start_path,
            root=root,
            target=target,
            suite_ids=suite_ids,
            db_path=db_path,
            onecv8=onecv8.path,
            ext_names=ext_names,
            tests_filter=[validated],
            ensure=ensure,
            breakpoints=bp_list,
            debugger_url=debugger_url,
            discover=discover,
            spawn_fn=spawn_unit_tests_fn,
            targets_timeout=targets_timeout,
        )

    runner = run_unit_tests_fn or run_unit_tests
    try:
        run_result = runner(
            onecv8.path,
            ib_path=db_path,
            work_dir=work_dir(root),
            extensions=ext_names,
            tests=[validated],
            timeout=timeout,
        )
    except YaxunitError as exc:
        return _fail(
            started=started,
            root=root,
            runtime_path=db_path,
            config_id=target.config_id,
            runtime_id=target.runtime_id,
            suite_ids=suite_ids,
            diagnostics=_map_adapter_error(exc),
            runner_ensure=ensure.to_payload() if ensure is not None else None,
        )

    return _result_from_run(
        started=started,
        root=root,
        target=target,
        suite_ids=suite_ids,
        run=run_result,
        ensure=ensure,
    )


def _teardown_debug_after_test(
    start_path: Path,
    root: Path,
    *,
    config_id: str | None,
    runtime_id: str | None,
    is_alive: IsAliveFn | None = None,
) -> list[Diagnostic]:
    """Detach ping/session/our dbgs after test client exit (mirror ``runtime stop``)."""
    from core.debug.ops import has_debug_state, teardown_debug

    if not has_debug_state(root):
        return []
    try:
        result = teardown_debug(
            start_path,
            config_id=config_id,
            runtime_id=runtime_id,
            is_alive=is_alive,
        )
    except Exception as exc:  # noqa: BLE001 — wait must still return jUnit
        return [
            warning(
                f"не удалось полностью остановить debug: {exc}",
                code=CODE_WAIT_TIMEOUT,
                source="test",
            )
        ]
    diags: list[Diagnostic] = []
    for diag in result.diagnostics:
        if diag.get("severity") == "error":
            diags.append(
                warning(
                    str(diag.get("message", "")),
                    code=diag.get("code"),
                    source="test",
                    suggestion=diag.get("suggestion"),
                )
            )
        else:
            diags.append(diag)
    return diags


def wait_tests(
    start: Path | None = None,
    *,
    timeout: float = DEFAULT_WAIT_TIMEOUT_SEC,
    poll_interval: float = 0.5,
    is_alive: IsAliveFn | None = None,
) -> TestResult:
    """
    Wait for detach ``test.run --debug`` process exit, then parse jUnit (#147).

    Reads ``.1c-dev/test/run.meta.json``; writes ``last-result.json``; clears meta.
    After the test client exits (success or jUnit failure), tears down debug
    state like ``runtime stop`` (ping → detach → our dbgs). Timeout while the
    process is still alive does **not** teardown — agent may still ``debug.wait``.
    """
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    alive = is_alive or is_running

    manifest = detect_manifest(start_path)
    if manifest is None:
        return _fail(
            started=started,
            diagnostics=[
                error(
                    f"Манифест проекта не найден ({HOME_MANIFEST_REL})",
                    code=CODE_PROJECT,
                    source="test",
                )
            ],
        )
    root = scope_root_from_manifest(manifest)
    meta, meta_diags = load_run_meta(root)
    if meta is None:
        return _fail(started=started, root=root, diagnostics=meta_diags)

    config_id = str(meta["configId"]) if isinstance(meta.get("configId"), str) else None
    runtime_id = str(meta["runtimeId"]) if isinstance(meta.get("runtimeId"), str) else None
    suite_ids = (
        [str(s) for s in meta["suiteIds"]]
        if isinstance(meta.get("suiteIds"), list)
        else []
    )

    pid_raw = meta.get("pid")
    if not isinstance(pid_raw, int) or pid_raw <= 0:
        clear_run_meta(root)
        teardown_diags = _teardown_debug_after_test(
            start_path,
            root,
            config_id=config_id,
            runtime_id=runtime_id,
            is_alive=is_alive,
        )
        return _fail(
            started=started,
            root=root,
            config_id=config_id,
            runtime_id=runtime_id,
            suite_ids=suite_ids,
            diagnostics=[
                error(
                    "run.meta.json: некорректный pid",
                    code=CODE_PROJECT,
                    source="test",
                ),
                *teardown_diags,
            ],
        )

    deadline = time.perf_counter() + max(0.0, timeout)
    while alive(pid_raw):
        if time.perf_counter() >= deadline:
            return _fail(
                started=started,
                root=root,
                config_id=config_id,
                runtime_id=runtime_id,
                suite_ids=suite_ids,
                diagnostics=[
                    error(
                        f"таймаут ожидания завершения тестов ({timeout:g}s), pid={pid_raw}",
                        code=CODE_WAIT_TIMEOUT,
                        source="test",
                        suggestion="debug continue / увеличьте --timeout; debug не сброшен",
                    )
                ],
            )
        time.sleep(poll_interval)

    # Client exited — always tear down debug (like runtime stop), then collect jUnit.
    teardown_diags = _teardown_debug_after_test(
        start_path,
        root,
        config_id=config_id,
        runtime_id=runtime_id,
        is_alive=is_alive,
    )

    report_raw = meta.get("reportPath")
    exit_raw = meta.get("exitCodePath")
    log_raw = meta.get("logPath")
    out_raw = meta.get("outLogPath")
    if not all(isinstance(x, str) and x for x in (report_raw, exit_raw, log_raw, out_raw)):
        clear_run_meta(root)
        return _fail(
            started=started,
            root=root,
            config_id=config_id,
            runtime_id=runtime_id,
            suite_ids=suite_ids,
            diagnostics=[
                error(
                    "run.meta.json: отсутствуют пути артефактов YaXUnit",
                    code=CODE_PROJECT,
                    source="test",
                ),
                *teardown_diags,
            ],
        )

    argv_raw = meta.get("argv")
    argv = [str(x) for x in argv_raw] if isinstance(argv_raw, list) else []
    try:
        run_result = collect_unit_tests_result(
            report_path=Path(str(report_raw)),
            exit_code_path=Path(str(exit_raw)),
            log_path=Path(str(log_raw)),
            out_log_path=Path(str(out_raw)),
            process_exit_code=None,
            argv=argv,
        )
    except YaxunitError as exc:
        clear_run_meta(root)
        return _fail(
            started=started,
            root=root,
            config_id=config_id,
            runtime_id=runtime_id,
            suite_ids=suite_ids,
            diagnostics=[*_map_adapter_error(exc), *teardown_diags],
        )

    clear_run_meta(root)
    status = run_result.status
    result = TestResult(
        status=status,
        duration=time.perf_counter() - started,
        root=root,
        config_id=config_id,
        runtime_id=runtime_id,
        suite_ids=suite_ids,
        passed=run_result.passed,
        failed=run_result.failed,
        error=run_result.error,
        skipped=run_result.skipped,
        total=run_result.total,
        duration_sec=run_result.duration_sec,
        tests=_cases_to_dicts(run_result.tests),
        report_path=str(run_result.report_path) if run_result.report_path else None,
        debug_enabled=False,
        debugger_url=None,
        session_id=None,
        diagnostics=list(teardown_diags),
        exit_code=exit_code_for_run_status(status, total=run_result.total),
    )
    save_last_result(root, result)
    return result


def ensure_runner(
    start: Path | None = None,
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
    discover: DiscoverFn | None = None,
    ensure_runner_fn: EnsureRunnerFn | None = None,
) -> TestResult:
    """
    Explicit ``1c-dev yaxunit ensure``: load YAXUNIT from cache + safe-mode off.

    Does **not** call ``build`` and does not run tests (ADR-029 §7a).
    """
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    root, _data, target, err = _load_project(
        start_path,
        started=started,
        config_id=config_id,
        runtime_id=runtime_id,
        require_runtime=True,
    )
    if err is not None:
        return err

    if target.runtime_rel is None:
        return _fail(
            started=started,
            root=root,
            config_id=target.config_id,
            diagnostics=[
                error(
                    "Не удалось разрешить путь runtime",
                    code=CODE_PROJECT,
                    source="test",
                )
            ],
        )
    db_path = (root / target.runtime_rel).resolve()

    # Explicit command is unconditional: suites only narrow down the implicit preflight.
    ensure = _ensure_runner_step(
        root=root,
        target=target,
        selected=None,
        db_path=db_path,
        skip=False,
        discover=discover,
        ensure_fn=ensure_runner_fn,
    )
    assert ensure is not None
    diagnostics = list(ensure.diagnostics)
    if ensure.failed:
        return _fail(
            started=started,
            root=root,
            runtime_path=db_path,
            config_id=target.config_id,
            runtime_id=target.runtime_id,
            diagnostics=diagnostics,
            runner_ensure=ensure.to_payload(),
        )
    return TestResult(
        status="ok",
        diagnostics=diagnostics,
        duration=time.perf_counter() - started,
        root=root,
        runtime_path=db_path,
        config_id=target.config_id,
        runtime_id=target.runtime_id,
        runner_ensure=ensure.to_payload(),
        exit_code=SUCCESS,
    )
