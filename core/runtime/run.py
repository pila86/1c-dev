"""Runtime client lifecycle: start / stop / status (ADR-019)."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from adapters.platform import DiscoveryResult, discover_environment
from adapters.platform_1cv8 import (
    IsRunningFn,
    SpawnFn,
    TerminateFn,
    is_running,
    start_enterprise_client,
    stop_client,
)
from adapters.platform_1cv8.constants import MODE_ENTERPRISE
from adapters.platform_ibcmd import infobase_exists
from core.diagnostics import error
from core.project.detect import detect_manifest
from core.project.load import load_manifest
from core.runtime.constants import (
    CODE_CLIENT_FAILED,
    CODE_IB_MISSING,
    CODE_ONECV8_MISSING,
    CODE_PROJECT,
)
from core.runtime.result import RuntimeResult
from core.runtime.state import clear_state, read_meta, read_pid, write_state


def _gui_suggestion() -> str:
    if sys.platform == "win32":
        return "Запускайте на машине с интерактивной GUI-сессией Windows."
    return (
        "Нужен графический дисплей (DISPLAY). "
        "На headless-хосте запустите клиент в сессии с GUI."
    )


def _resolve_project(
    start: Path,
    *,
    started: float,
) -> tuple[Path, Path, RuntimeResult | None]:
    """Return (root, db_path, error_result_or_None)."""
    manifest_path = detect_manifest(start)
    if manifest_path is None:
        return (
            start,
            start,
            RuntimeResult(
                status="failed",
                duration=time.perf_counter() - started,
                diagnostics=[
                    error(
                        "Файл 1c.project.yaml не найден",
                        code=CODE_PROJECT,
                        source="runtime",
                        suggestion="Выполните 1c-dev init --type configuration",
                    )
                ],
            ),
        )

    data, load_diags = load_manifest(manifest_path)
    if data is None:
        return (
            manifest_path.parent,
            manifest_path.parent,
            RuntimeResult(
                status="failed",
                duration=time.perf_counter() - started,
                root=manifest_path.parent,
                diagnostics=list(load_diags)
                or [
                    error(
                        "Не удалось прочитать манифест",
                        code=CODE_PROJECT,
                        file=str(manifest_path.name),
                        source="runtime",
                    )
                ],
            ),
        )

    root = manifest_path.parent
    runtime_raw = data.get("runtime")
    runtime: dict[str, Any] = runtime_raw if isinstance(runtime_raw, dict) else {}
    runtime_rel = str(runtime.get("path") or ".runtime/ib")
    db_path = (root / runtime_rel).resolve()
    return root, db_path, None


def _alive_snapshot(
    root: Path,
    *,
    is_alive: IsRunningFn,
) -> tuple[bool, int | None, str, bool]:
    """Return (running, pid, mode, debug_enabled); clear stale state."""
    pid = read_pid(root)
    meta = read_meta(root)
    mode = str(meta.get("mode") or MODE_ENTERPRISE)
    debug_raw = meta.get("debug")
    debug_enabled = bool(
        debug_raw.get("enabled") if isinstance(debug_raw, dict) else False
    )
    if pid is None:
        return False, None, mode, debug_enabled
    if is_alive(pid):
        return True, pid, mode, debug_enabled
    clear_state(root)
    return False, None, MODE_ENTERPRISE, False


def run_status(
    start: Path | None = None,
    *,
    is_alive: IsRunningFn | None = None,
) -> RuntimeResult:
    """Report whether the detached ENTERPRISE client is running."""
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    alive = is_alive or is_running

    root, db_path, err = _resolve_project(start_path, started=started)
    if err is not None:
        return err

    running, pid, mode, debug_enabled = _alive_snapshot(root, is_alive=alive)
    return RuntimeResult(
        status="ok",
        duration=time.perf_counter() - started,
        root=root,
        runtime_path=db_path,
        running=running,
        pid=pid,
        mode=mode if running else None,
        debug_enabled=debug_enabled if running else False,
    )


def run_stop(
    start: Path | None = None,
    *,
    is_alive: IsRunningFn | None = None,
    terminate_fn: TerminateFn | None = None,
) -> RuntimeResult:
    """Stop the detached ENTERPRISE client if running."""
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    alive = is_alive or is_running

    root, db_path, err = _resolve_project(start_path, started=started)
    if err is not None:
        return err

    running, pid, mode, debug_enabled = _alive_snapshot(root, is_alive=alive)
    if not running or pid is None:
        clear_state(root)
        return RuntimeResult(
            status="ok",
            duration=time.perf_counter() - started,
            root=root,
            runtime_path=db_path,
            running=False,
            pid=None,
            mode=None,
            debug_enabled=False,
        )

    ok = stop_client(pid, terminate_fn=terminate_fn)
    clear_state(root)
    if not ok and alive(pid):
        return RuntimeResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            runtime_path=db_path,
            running=True,
            pid=pid,
            mode=mode,
            debug_enabled=debug_enabled,
            diagnostics=[
                error(
                    f"Не удалось остановить процесс 1cv8 (pid={pid})",
                    code=CODE_CLIENT_FAILED,
                    source="runtime",
                )
            ],
        )

    return RuntimeResult(
        status="ok",
        duration=time.perf_counter() - started,
        root=root,
        runtime_path=db_path,
        running=False,
        pid=None,
        mode=None,
        debug_enabled=False,
    )


def run_start(
    start: Path | None = None,
    *,
    debug: bool = False,
    discover: Callable[[], DiscoveryResult] | None = None,
    spawn: SpawnFn | None = None,
    is_alive: IsRunningFn | None = None,
    settle_seconds: float = 0.3,
) -> RuntimeResult:
    """Detach-start ENTERPRISE client against the project file IB."""
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    alive = is_alive or is_running

    root, db_path, err = _resolve_project(start_path, started=started)
    if err is not None:
        return err

    running, pid, mode, debug_enabled = _alive_snapshot(root, is_alive=alive)
    if running and pid is not None:
        return RuntimeResult(
            status="ok",
            duration=time.perf_counter() - started,
            root=root,
            runtime_path=db_path,
            running=True,
            pid=pid,
            mode=mode,
            debug_enabled=debug_enabled,
        )

    if not infobase_exists(db_path):
        return RuntimeResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            runtime_path=db_path,
            diagnostics=[
                error(
                    f"File IB не найдена: нет маркера 1Cv8.1CD в {db_path}",
                    code=CODE_IB_MISSING,
                    source="runtime",
                    suggestion="Сначала выполните 1c-dev build или 1c-dev runtime load",
                )
            ],
        )

    discovery = (discover or discover_environment)()
    onecv8 = discovery.onecv8
    if not onecv8.found or onecv8.path is None:
        return RuntimeResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            runtime_path=db_path,
            diagnostics=[
                error(
                    "1cv8 не найден",
                    code=CODE_ONECV8_MISSING,
                    source="platform",
                    suggestion=(
                        "Установите платформу 1С и добавьте 1cv8 в PATH "
                        "(или в стандартный каталог установки)."
                    ),
                )
            ],
        )

    try:
        new_pid, _argv = start_enterprise_client(
            onecv8.path,
            ib_path=db_path,
            debug=debug,
            spawn=spawn,
            settle_seconds=settle_seconds,
            is_alive=alive,
        )
    except RuntimeError as exc:
        clear_state(root)
        return RuntimeResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            runtime_path=db_path,
            diagnostics=[
                error(
                    str(exc),
                    code=CODE_CLIENT_FAILED,
                    source="runtime",
                    suggestion=_gui_suggestion(),
                )
            ],
        )
    except OSError as exc:
        clear_state(root)
        return RuntimeResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            runtime_path=db_path,
            diagnostics=[
                error(
                    f"Не удалось запустить 1cv8: {exc}",
                    code=CODE_CLIENT_FAILED,
                    source="runtime",
                    suggestion=_gui_suggestion(),
                )
            ],
        )

    write_state(root, pid=new_pid, debug=debug, mode=MODE_ENTERPRISE)
    return RuntimeResult(
        status="ok",
        duration=time.perf_counter() - started,
        root=root,
        runtime_path=db_path,
        running=True,
        pid=new_pid,
        mode=MODE_ENTERPRISE,
        debug_enabled=debug,
    )
