"""Check orchestration: ibcmd metadata + Designer /CheckModules (ADR-009 / ADR-030)."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from adapters.platform import DiscoveryResult, discover_environment
from adapters.platform_1cv8 import CheckModulesError, check_modules
from adapters.platform_ibcmd import IbcmdError, RunFn, check_config, infobase_exists
from adapters.platform_ibcmd.constants import (
    CODE_CHECK_FAILED,
    CODE_CHECK_IB_MISSING,
    CODE_CHECK_IBCMD_MISSING,
    CODE_CHECK_ONECV8_MISSING,
    CODE_CHECK_PROJECT,
    IBCMD_DATA_REL,
)
from core.check.result import CheckResult
from core.diagnostics import Diagnostic, error
from core.project.constants import HOME_MANIFEST_REL
from core.project.detect import detect_manifest
from core.project.load import load_manifest
from core.project.paths import default_runtime_rel, scope_root_from_manifest

CheckFn = Callable[..., Any]
ModulesFn = Callable[..., Any]

_OUT_REL = ".1c-dev/runtime/check-modules.out"


def run_check(
    start: Path | None = None,
    *,
    modes: Sequence[str] | None = None,
    run: RunFn | None = None,
    check_fn: CheckFn | None = None,
    modules_fn: ModulesFn | None = None,
    discover: Callable[[], DiscoveryResult] | None = None,
) -> CheckResult:
    """
    Run platform check on an existing file IB: ibcmd metadata + /CheckModules.

    run / check_fn / modules_fn / discover: injectable for tests.
    """
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()

    manifest_path = detect_manifest(start_path)
    if manifest_path is None:
        return CheckResult(
            status="failed",
            duration=time.perf_counter() - started,
            diagnostics=[
                error(
                    f"Файл {HOME_MANIFEST_REL} не найден",
                    code=CODE_CHECK_PROJECT,
                    source="runtime",
                    suggestion="Выполните 1c-dev init --type configuration",
                )
            ],
        )

    data, load_diags = load_manifest(manifest_path)
    if data is None:
        return CheckResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=scope_root_from_manifest(manifest_path),
            diagnostics=list(load_diags)
            or [
                error(
                    "Не удалось прочитать манифест",
                    code=CODE_CHECK_PROJECT,
                    source="runtime",
                )
            ],
        )

    root = scope_root_from_manifest(manifest_path)
    runtime_rel = default_runtime_rel(data)
    db_path = (root / runtime_rel).resolve()
    data_path = (root / IBCMD_DATA_REL).resolve()
    out_log = (root / _OUT_REL).resolve()

    discovery = (discover or discover_environment)()
    ibcmd_info = discovery.ibcmd
    if not ibcmd_info.found or ibcmd_info.path is None:
        return CheckResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            runtime_path=db_path,
            diagnostics=[
                error(
                    "ibcmd не найден",
                    code=CODE_CHECK_IBCMD_MISSING,
                    source="platform",
                    suggestion=(
                        "Установите платформу 1С и добавьте ibcmd в PATH "
                        "(или в стандартный каталог установки)."
                    ),
                )
            ],
        )

    onecv8_info = discovery.onecv8
    if not onecv8_info.found or onecv8_info.path is None:
        return CheckResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            runtime_path=db_path,
            diagnostics=[
                error(
                    "1cv8 не найден",
                    code=CODE_CHECK_ONECV8_MISSING,
                    source="platform",
                    suggestion=(
                        "Установите платформу 1С и добавьте 1cv8 в PATH "
                        "(нужен для /CheckModules)."
                    ),
                )
            ],
        )

    if not infobase_exists(db_path):
        return CheckResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            runtime_path=db_path,
            diagnostics=[
                error(
                    f"File IB не найдена: {runtime_rel}",
                    code=CODE_CHECK_IB_MISSING,
                    source="runtime",
                    suggestion="Сначала выполните 1c-dev build",
                )
            ],
        )

    diagnostics: list[Diagnostic] = []
    steps: list[str] = []

    try:
        if check_fn is not None:
            check_fn(
                ibcmd_info.path,
                db_path=db_path,
                data_path=data_path,
                run=run,
            )
        else:
            check_config(
                ibcmd_info.path,
                db_path=db_path,
                data_path=data_path,
                run=run,
            )
    except IbcmdError as exc:
        diagnostics.extend(
            list(exc.diagnostics)
            or [
                error(
                    exc.message,
                    code=exc.code or CODE_CHECK_FAILED,
                    source="platform",
                )
            ]
        )
    steps.append("metadata")

    modules_runner = modules_fn or check_modules
    try:
        modules_runner(
            onecv8_info.path,
            ib_path=db_path,
            out_log=out_log,
            modes=modes,
        )
    except CheckModulesError as exc:
        diagnostics.extend(
            list(exc.diagnostics)
            or [
                error(
                    exc.message,
                    code=exc.code or CODE_CHECK_FAILED,
                    source="platform",
                )
            ]
        )
    steps.append("modules")

    return CheckResult(
        status="ok" if not diagnostics else "failed",
        duration=time.perf_counter() - started,
        root=root,
        runtime_path=db_path,
        steps=steps,
        diagnostics=diagnostics,
    )
