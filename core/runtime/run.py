"""Runtime client lifecycle: start / stop / status (ADR-019)."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from adapters.platform import DiscoveryResult, discover_environment
from adapters.platform_1cv8 import (
    IsRunningFn,
    SpawnFn,
    TerminateFn,
    is_running,
    start_enterprise_client,
    stop_client,
)
from adapters.platform_1cv8.constants import (
    CLIENT_THICK,
    CLIENT_THIN,
    MODE_ENTERPRISE,
)
from adapters.platform_ibcmd import infobase_exists
from core.diagnostics import error
from core.project.constants import HOME_MANIFEST_REL
from core.project.detect import detect_manifest
from core.project.load import load_manifest
from core.project.paths import scope_root_from_manifest
from core.project.resolve import resolve_config_runtime
from core.runtime.constants import (
    CODE_CLIENT_FAILED,
    CODE_IB_MISSING,
    CODE_ONECV8_MISSING,
    CODE_ONECV8C_MISSING,
    CODE_PROJECT,
)
from core.runtime.result import RuntimeResult
from core.runtime.state import clear_state, read_meta, read_pid, write_state

ClientKind = Literal["thick", "thin"]


def _gui_suggestion() -> str:
    if sys.platform == "win32":
        return "Запускайте на машине с интерактивной GUI-сессией Windows."
    return (
        "Нужен графический дисплей (DISPLAY). "
        "На headless-хосте запустите клиент в сессии с GUI."
    )


def _normalize_client(client: str) -> ClientKind:
    value = client.strip().lower()
    if value == CLIENT_THIN:
        return "thin"
    return "thick"


def _resolve_project(
    start: Path,
    *,
    started: float,
    config_id: str | None = None,
    runtime_id: str | None = None,
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
                        f"Файл {HOME_MANIFEST_REL} не найден",
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
            scope_root_from_manifest(manifest_path),
            scope_root_from_manifest(manifest_path),
            RuntimeResult(
                status="failed",
                duration=time.perf_counter() - started,
                root=scope_root_from_manifest(manifest_path),
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

    root = scope_root_from_manifest(manifest_path)
    target, resolve_diags = resolve_config_runtime(
        data,
        config_id=config_id,
        runtime_id=runtime_id,
        require_runtime=True,
    )
    if target is None or target.runtime_rel is None:
        return (
            root,
            root,
            RuntimeResult(
                status="failed",
                duration=time.perf_counter() - started,
                root=root,
                diagnostics=list(resolve_diags)
                or [
                    error(
                        "Не удалось разрешить --config/--runtime",
                        code=CODE_PROJECT,
                        source="runtime",
                    )
                ],
            ),
        )
    db_path = (root / target.runtime_rel).resolve()
    return root, db_path, None


def _alive_snapshot(
    root: Path,
    *,
    is_alive: IsRunningFn,
) -> tuple[bool, int | None, str, str, bool]:
    """Return (running, pid, mode, client, debug_enabled); clear stale state."""
    pid = read_pid(root)
    meta = read_meta(root)
    mode = str(meta.get("mode") or MODE_ENTERPRISE)
    client = str(meta.get("client") or CLIENT_THICK)
    debug_raw = meta.get("debug")
    debug_enabled = bool(
        debug_raw.get("enabled") if isinstance(debug_raw, dict) else False
    )
    if pid is None:
        return False, None, mode, client, debug_enabled
    if is_alive(pid):
        return True, pid, mode, client, debug_enabled
    clear_state(root)
    return False, None, MODE_ENTERPRISE, CLIENT_THICK, False


def run_status(
    start: Path | None = None,
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
    is_alive: IsRunningFn | None = None,
) -> RuntimeResult:
    """Report whether the detached ENTERPRISE client is running."""
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    alive = is_alive or is_running

    root, db_path, err = _resolve_project(
        start_path,
        started=started,
        config_id=config_id,
        runtime_id=runtime_id,
    )
    if err is not None:
        return err

    running, pid, mode, client, debug_enabled = _alive_snapshot(root, is_alive=alive)
    return RuntimeResult(
        status="ok",
        duration=time.perf_counter() - started,
        root=root,
        runtime_path=db_path,
        running=running,
        pid=pid,
        mode=mode if running else None,
        client=client if running else None,
        debug_enabled=debug_enabled if running else False,
    )


def run_stop(
    start: Path | None = None,
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
    is_alive: IsRunningFn | None = None,
    terminate_fn: TerminateFn | None = None,
) -> RuntimeResult:
    """Stop the detached ENTERPRISE client if running."""
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    alive = is_alive or is_running

    root, db_path, err = _resolve_project(
        start_path,
        started=started,
        config_id=config_id,
        runtime_id=runtime_id,
    )
    if err is not None:
        return err

    running, pid, mode, client, debug_enabled = _alive_snapshot(root, is_alive=alive)
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
            client=None,
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
            client=client,
            debug_enabled=debug_enabled,
            diagnostics=[
                error(
                    f"Не удалось остановить процесс клиента 1С (pid={pid})",
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
        client=None,
        debug_enabled=False,
    )


def run_start(
    start: Path | None = None,
    *,
    client: str = CLIENT_THICK,
    debug: bool = False,
    config_id: str | None = None,
    runtime_id: str | None = None,
    discover: Callable[[], DiscoveryResult] | None = None,
    spawn: SpawnFn | None = None,
    is_alive: IsRunningFn | None = None,
    settle_seconds: float = 0.3,
) -> RuntimeResult:
    """Detach-start ENTERPRISE client (thick or thin) against the project file IB."""
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    alive = is_alive or is_running
    client_kind = _normalize_client(client)

    root, db_path, err = _resolve_project(
        start_path,
        started=started,
        config_id=config_id,
        runtime_id=runtime_id,
    )
    if err is not None:
        return err

    running, pid, mode, running_client, debug_enabled = _alive_snapshot(
        root, is_alive=alive
    )
    if running and pid is not None:
        if running_client == client_kind:
            return RuntimeResult(
                status="ok",
                duration=time.perf_counter() - started,
                root=root,
                runtime_path=db_path,
                running=True,
                pid=pid,
                mode=mode,
                client=running_client,
                debug_enabled=debug_enabled,
            )
        return RuntimeResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            runtime_path=db_path,
            running=True,
            pid=pid,
            mode=mode,
            client=running_client,
            debug_enabled=debug_enabled,
            diagnostics=[
                error(
                    (
                        f"Уже запущен клиент client={running_client} (pid={pid}); "
                        f"запрошен client={client_kind}"
                    ),
                    code=CODE_CLIENT_FAILED,
                    source="runtime",
                    suggestion="Выполните 1c-dev runtime stop и повторите start",
                )
            ],
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
    if client_kind == CLIENT_THIN:
        tool = discovery.onecv8c
        missing_code = CODE_ONECV8C_MISSING
        missing_name = "1cv8c"
        missing_suggestion = (
            "Установите платформу 1С с тонким клиентом и добавьте 1cv8c в PATH "
            "(обычно рядом с 1cv8 в каталоге установки)."
        )
    else:
        tool = discovery.onecv8
        missing_code = CODE_ONECV8_MISSING
        missing_name = "1cv8"
        missing_suggestion = (
            "Установите платформу 1С и добавьте 1cv8 в PATH "
            "(или в стандартный каталог установки)."
        )

    if not tool.found or tool.path is None:
        return RuntimeResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            runtime_path=db_path,
            diagnostics=[
                error(
                    f"{missing_name} не найден",
                    code=missing_code,
                    source="platform",
                    suggestion=missing_suggestion,
                )
            ],
        )

    try:
        new_pid, _argv = start_enterprise_client(
            tool.path,
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
                    f"Не удалось запустить {missing_name}: {exc}",
                    code=CODE_CLIENT_FAILED,
                    source="runtime",
                    suggestion=_gui_suggestion(),
                )
            ],
        )

    write_state(
        root,
        pid=new_pid,
        debug=debug,
        mode=MODE_ENTERPRISE,
        client=client_kind,
    )
    return RuntimeResult(
        status="ok",
        duration=time.perf_counter() - started,
        root=root,
        runtime_path=db_path,
        running=True,
        pid=new_pid,
        mode=MODE_ENTERPRISE,
        client=client_kind,
        debug_enabled=debug,
    )
