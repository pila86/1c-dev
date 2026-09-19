"""Check orchestration: project + ibcmd config check (ADR-009)."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from adapters.platform import DiscoveryResult, discover_environment
from adapters.platform_ibcmd import IbcmdError, RunFn, check_config, infobase_exists
from adapters.platform_ibcmd.constants import (
    CODE_CHECK_FAILED,
    CODE_CHECK_IB_MISSING,
    CODE_CHECK_IBCMD_MISSING,
    CODE_CHECK_PROJECT,
    IBCMD_DATA_REL,
)
from core.check.result import CheckResult
from core.diagnostics import error
from core.project.detect import detect_manifest
from core.project.load import load_manifest

CheckFn = Callable[..., Any]


def run_check(
    start: Path | None = None,
    *,
    run: RunFn | None = None,
    check_fn: CheckFn | None = None,
    discover: Callable[[], DiscoveryResult] | None = None,
) -> CheckResult:
    """
    Run platform config check on an existing file IB via ibcmd.

    run / check_fn / discover: injectable for tests.
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
                    "Файл 1c.project.yaml не найден",
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
            root=manifest_path.parent,
            diagnostics=list(load_diags)
            or [
                error(
                    "Не удалось прочитать манифест",
                    code=CODE_CHECK_PROJECT,
                    file=str(manifest_path.name),
                    source="runtime",
                )
            ],
        )

    root = manifest_path.parent
    runtime_raw = data.get("runtime")
    runtime: dict[str, Any] = runtime_raw if isinstance(runtime_raw, dict) else {}

    runtime_rel = str(runtime.get("path") or ".runtime/ib")
    db_path = (root / runtime_rel).resolve()
    data_path = (root / IBCMD_DATA_REL).resolve()

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
        return CheckResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            runtime_path=db_path,
            diagnostics=list(exc.diagnostics)
            or [
                error(
                    exc.message,
                    code=exc.code or CODE_CHECK_FAILED,
                    source="platform",
                )
            ],
        )

    return CheckResult(
        status="ok",
        duration=time.perf_counter() - started,
        root=root,
        runtime_path=db_path,
    )
