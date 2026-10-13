"""dbgs lifecycle: start / stop / status (ADR-031 / #140)."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from adapters.debug_http.client import DebugHttpClient, TransportFn
from adapters.debug_http.errors import DebugHttpError
from adapters.platform import DiscoveryResult, discover_environment
from adapters.platform_1cv8 import IsRunningFn, TerminateFn, is_running, terminate
from core.debug.constants import (
    CODE_DBGS_MISSING,
    CODE_DBGS_UNREACHABLE,
    CODE_PROJECT,
    DEFAULT_HOST,
    SOURCE_DEBUG,
)
from core.debug.result import DebugResult, exit_code_for_result
from core.debug.state import (
    alive_server,
    clear_server_state,
    manifest_debug_settings,
    notify_path,
    write_server_state,
)
from core.diagnostics import Diagnostic, error
from core.exit_codes import SUCCESS

SpawnDbgsFn = Callable[[Sequence[str], Path], int]
DiscoverFn = Callable[[], DiscoveryResult]


def _read_notify_text(path: Path) -> str:
    if not path.is_file():
        return ""
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16").strip()
    return raw.decode("utf-8", errors="replace").strip()


def _port_free(host: str, port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) != 0


def default_spawn_dbgs(argv: Sequence[str], log_path: Path) -> int:
    """Detach-start ``dbgs``; return pid."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = open(log_path, "wb")  # noqa: SIM115 — lives with process
    proc = subprocess.Popen(
        list(argv),
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return int(proc.pid)


def build_dbgs_argv(
    dbgs: Path,
    *,
    host: str,
    port: int,
    notify: Path,
    password: str | None = None,
) -> list[str]:
    argv = [
        str(dbgs),
        f"--addr={host}",
        f"--port={port}",
        f"--notify={notify}",
    ]
    if password:
        argv.append(f"--password={password}")
    return argv


def server_status(
    root: Path,
    *,
    started: float,
    config_id: str | None = None,
    runtime_id: str | None = None,
    is_alive: IsRunningFn | None = None,
    transport: TransportFn | None = None,
) -> DebugResult:
    running, pid, meta = alive_server(root, is_alive=is_alive)
    host = meta.get("host") if isinstance(meta.get("host"), str) else None
    port = meta.get("port") if isinstance(meta.get("port"), int) else None
    url = meta.get("url") if isinstance(meta.get("url"), str) else None
    if running and url:
        try:
            DebugHttpClient(url, transport=transport).test()
        except DebugHttpError as exc:
            return DebugResult(
                status="failed",
                duration=time.perf_counter() - started,
                root=root,
                config_id=config_id,
                runtime_id=runtime_id,
                host=host,
                port=port,
                url=url,
                pid=pid,
                running=True,
                diagnostics=list(exc.diagnostics),
                exit_code=exit_code_for_result("failed", list(exc.diagnostics)),
            )
    return DebugResult(
        status="ok",
        duration=time.perf_counter() - started,
        root=root,
        config_id=config_id,
        runtime_id=runtime_id,
        host=host,
        port=port,
        url=url,
        pid=pid,
        running=running,
        exit_code=SUCCESS,
    )


def server_start(
    root: Path,
    data: dict[str, Any],
    *,
    started: float,
    host: str | None = None,
    port: int | None = None,
    password: str | None = None,
    config_id: str | None = None,
    runtime_id: str | None = None,
    discover: DiscoverFn | None = None,
    spawn: SpawnDbgsFn | None = None,
    is_alive: IsRunningFn | None = None,
    transport: TransportFn | None = None,
    settle_seconds: float = 0.1,
    notify_timeout: float = 5.0,
) -> DebugResult:
    settings = manifest_debug_settings(data)
    host_v = (host or settings["host"] or DEFAULT_HOST).strip() or DEFAULT_HOST
    port_v = port if port is not None else settings["port"]
    if port_v is None:
        diags = [
            error(
                "порт dbgs не задан (нет тихого default 1550)",
                code=CODE_PROJECT,
                source=SOURCE_DEBUG,
                suggestion="укажите --port или debug.port в .1c-dev/project.yaml",
            )
        ]
        return DebugResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            config_id=config_id,
            runtime_id=runtime_id,
            host=host_v,
            diagnostics=diags,
            exit_code=exit_code_for_result("failed", diags),
        )

    running, pid, meta = alive_server(root, is_alive=is_alive)
    if running and pid is not None:
        url = meta.get("url") if isinstance(meta.get("url"), str) else f"http://{host_v}:{port_v}"
        return DebugResult(
            status="ok",
            duration=time.perf_counter() - started,
            root=root,
            config_id=config_id,
            runtime_id=runtime_id,
            host=str(meta.get("host") or host_v),
            port=int(meta["port"]) if isinstance(meta.get("port"), int) else port_v,
            url=url,
            pid=pid,
            running=True,
            exit_code=SUCCESS,
        )

    if not _port_free(host_v, int(port_v)):
        diags = [
            error(
                f"порт {port_v} занят (не нашим dbgs)",
                code=CODE_DBGS_UNREACHABLE,
                source=SOURCE_DEBUG,
                suggestion="выберите другой --port / debug.port (1550 часто занят кластером)",
            )
        ]
        return DebugResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            config_id=config_id,
            runtime_id=runtime_id,
            host=host_v,
            port=int(port_v),
            diagnostics=diags,
            exit_code=exit_code_for_result("failed", diags),
        )

    discovery = (discover or discover_environment)()
    if not discovery.dbgs.found or discovery.dbgs.path is None:
        diags = [
            error(
                "dbgs не найден",
                code=CODE_DBGS_MISSING,
                source="platform",
                suggestion=(
                    "установите платформу 1С с HTTP Debug Server "
                    "(dbgs рядом с 1cv8/ibcmd)"
                ),
            )
        ]
        return DebugResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            config_id=config_id,
            runtime_id=runtime_id,
            host=host_v,
            port=int(port_v),
            diagnostics=diags,
            exit_code=exit_code_for_result("failed", diags),
        )

    notify = notify_path(root)
    notify.parent.mkdir(parents=True, exist_ok=True)
    notify.unlink(missing_ok=True)
    argv = build_dbgs_argv(
        discovery.dbgs.path,
        host=host_v,
        port=int(port_v),
        notify=notify,
        password=password,
    )
    spawner = spawn or default_spawn_dbgs
    log_path = state_dir_log(root)
    try:
        new_pid = spawner(argv, log_path)
    except OSError as exc:
        diags = [
            error(
                f"не удалось запустить dbgs: {exc}",
                code=CODE_DBGS_UNREACHABLE,
                source=SOURCE_DEBUG,
            )
        ]
        return DebugResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            config_id=config_id,
            runtime_id=runtime_id,
            host=host_v,
            port=int(port_v),
            diagnostics=diags,
            exit_code=exit_code_for_result("failed", diags),
        )

    alive = is_alive or is_running
    deadline = time.perf_counter() + notify_timeout
    while time.perf_counter() < deadline:
        if notify.is_file() and notify.stat().st_size > 0:
            break
        if not alive(new_pid):
            diags = [
                error(
                    "dbgs завершился сразу после запуска",
                    code=CODE_DBGS_UNREACHABLE,
                    source=SOURCE_DEBUG,
                    suggestion=f"см. лог {log_path}",
                )
            ]
            clear_server_state(root)
            return DebugResult(
                status="failed",
                duration=time.perf_counter() - started,
                root=root,
                config_id=config_id,
                runtime_id=runtime_id,
                host=host_v,
                port=int(port_v),
                diagnostics=diags,
                exit_code=exit_code_for_result("failed", diags),
            )
        time.sleep(settle_seconds)
    else:
        # notify optional on some builds — still try HTTP test
        pass

    url = f"http://{host_v}:{port_v}"
    notify_text = _read_notify_text(notify)
    write_server_state(
        root,
        pid=new_pid,
        host=host_v,
        port=int(port_v),
        notify=notify_text or None,
    )
    try:
        DebugHttpClient(url, transport=transport).test()
    except DebugHttpError as exc:
        test_diags: list[Diagnostic] = list(exc.diagnostics)
        return DebugResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            config_id=config_id,
            runtime_id=runtime_id,
            host=host_v,
            port=int(port_v),
            url=url,
            pid=new_pid,
            running=alive(new_pid),
            diagnostics=test_diags,
            exit_code=exit_code_for_result("failed", test_diags),
        )

    return DebugResult(
        status="ok",
        duration=time.perf_counter() - started,
        root=root,
        config_id=config_id,
        runtime_id=runtime_id,
        host=host_v,
        port=int(port_v),
        url=url,
        pid=new_pid,
        running=True,
        exit_code=SUCCESS,
    )


def state_dir_log(root: Path) -> Path:
    from core.debug.state import state_dir

    return state_dir(root) / "dbgs.log"


def server_stop(
    root: Path,
    *,
    started: float,
    config_id: str | None = None,
    runtime_id: str | None = None,
    is_alive: IsRunningFn | None = None,
    terminate_fn: TerminateFn | None = None,
) -> DebugResult:
    running, pid, meta = alive_server(root, is_alive=is_alive)
    if not running or pid is None:
        clear_server_state(root)
        return DebugResult(
            status="ok",
            duration=time.perf_counter() - started,
            root=root,
            config_id=config_id,
            runtime_id=runtime_id,
            host=meta.get("host") if isinstance(meta.get("host"), str) else None,
            port=meta.get("port") if isinstance(meta.get("port"), int) else None,
            url=meta.get("url") if isinstance(meta.get("url"), str) else None,
            running=False,
            exit_code=SUCCESS,
        )

    stopper = terminate_fn or terminate
    alive = is_alive or is_running
    ok = stopper(pid)
    if alive(pid) and not ok:
        diags = [
            error(
                f"не удалось остановить dbgs pid={pid}",
                code=CODE_DBGS_UNREACHABLE,
                source=SOURCE_DEBUG,
            )
        ]
        return DebugResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            config_id=config_id,
            runtime_id=runtime_id,
            pid=pid,
            running=True,
            diagnostics=diags,
            exit_code=exit_code_for_result("failed", diags),
        )
    clear_server_state(root)
    return DebugResult(
        status="ok",
        duration=time.perf_counter() - started,
        root=root,
        config_id=config_id,
        runtime_id=runtime_id,
        running=False,
        exit_code=SUCCESS,
    )
